"""数据库连接与事务封装（标准库 sqlite3，无 ORM）。

FastAPI 是单进程多线程（uvicorn 默认单 worker 事件循环跑 sync handler），
连接按请求现取现用：check_same_thread=False + 短事务，够 POC 用。

凭证存储：AES-256-GCM 全加密（完整方案 §7），master key 从 env STORE_MASTER_KEY 读，
不入库不落盘；AAD 绑定 (user_id, skill_id) 防跨用户/跨技能互换（§13 权限隔离）。
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .models import SCHEMA

DB_PATH = Path(__file__).resolve().parent / "store.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """建表（幂等）+ user_skills 迁移（幂等）。"""
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate_user_skills_enabled(conn)


def _migrate_user_skills_enabled(conn: sqlite3.Connection) -> None:
    """user_skills 加 enabled 列（1=已启用，0=已选购但停用）。

    旧库缺列则 ALTER 补上，既有行默认 enabled=1（选购即启用，行为不变）。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(user_skills)")}
    if "enabled" not in cols:
        conn.execute("ALTER TABLE user_skills ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")


def _current_version(conn: sqlite3.Connection, user_id: str) -> int:
    row = conn.execute(
        "SELECT version FROM user_skill_versions WHERE user_id=?", (user_id,)
    ).fetchone()
    return int(row["version"]) if row else 0


def _bump_version(conn: sqlite3.Connection, user_id: str) -> int:
    """版本 +1 并返回新版本号（server 侧据此重建用户图）。"""
    conn.execute(
        """INSERT INTO user_skill_versions (user_id, version) VALUES (?,1)
           ON CONFLICT(user_id) DO UPDATE SET version = version + 1""",
        (user_id,),
    )
    return _current_version(conn, user_id)


def put_user_skills(conn: sqlite3.Connection, user_id: str, skill_ids: list[str]) -> int:
    """同一事务：替换选购 + version+1。返回新版本号（设计 §5.2）。

    PUT 是"全量替换"语义：传进来的 skill_ids 即最终列表；全部置 enabled=1（启用）。
    """
    conn.execute("DELETE FROM user_skills WHERE user_id=?", (user_id,))
    conn.executemany(
        "INSERT INTO user_skills (user_id, skill_id, enabled, enabled_at) VALUES (?,?,1,datetime('now'))",
        [(user_id, s) for s in skill_ids],
    )
    return _bump_version(conn, user_id)


def set_skill_enabled(conn: sqlite3.Connection, user_id: str, skill_id: str, enabled: bool) -> int:
    """单技能启/停。未选购时置 enabled=true 即自动选购（INSERT）；已选购只改 enabled。

    实际变更才 bump 版本；无变更（如停用不存在的技能）返回当前版本。
    """
    if enabled:
        conn.execute(
            """INSERT INTO user_skills (user_id, skill_id, enabled, enabled_at) VALUES (?,?,1,datetime('now'))
               ON CONFLICT(user_id, skill_id) DO UPDATE SET enabled=1""",
            (user_id, skill_id),
        )
    else:
        cur = conn.execute(
            "UPDATE user_skills SET enabled=0 WHERE user_id=? AND skill_id=?", (user_id, skill_id)
        )
        if cur.rowcount == 0:
            # 内置技能默认启用（没有 user_skills 行）。第一次关闭时必须落一条
            # enabled=0 的偏好，否则下次读取会再次按默认值显示为开启。
            skill = conn.execute(
                "SELECT publisher FROM skills WHERE skill_id=?", (skill_id,)
            ).fetchone()
            if not skill or skill["publisher"] != "builtin":
                return _current_version(conn, user_id)
            conn.execute(
                "INSERT INTO user_skills (user_id, skill_id, enabled, enabled_at) VALUES (?,?,0,datetime('now'))",
                (user_id, skill_id),
            )
    return _bump_version(conn, user_id)


def remove_skill(conn: sqlite3.Connection, user_id: str, skill_id: str) -> int:
    """兼容旧退订接口。

    手机端不再展示“退订”，只保留启用开关。若旧客户端仍调用退订，内置技能
    不能删除用户偏好（否则下次按默认值又会恢复启用），因此将其等价为停用；
    远程技能仍按旧语义删除选购和凭证。
    """
    skill = conn.execute("SELECT publisher FROM skills WHERE skill_id=?", (skill_id,)).fetchone()
    if skill and skill["publisher"] == "builtin":
        return set_skill_enabled(conn, user_id, skill_id, False)
    cur = conn.execute(
        "DELETE FROM user_skills WHERE user_id=? AND skill_id=?", (user_id, skill_id)
    )
    if cur.rowcount == 0:
        return _current_version(conn, user_id)
    conn.execute(
        "DELETE FROM user_skill_credentials WHERE user_id=? AND skill_id=?",
        (user_id, skill_id),
    )
    return _bump_version(conn, user_id)


# ---- 动态凭证：AES-256-GCM 加密存储（完整方案 §7.9 / §13）----


def _master_key() -> bytes:
    """AES-GCM 主密钥：从 env STORE_MASTER_KEY 读（不入库不落盘）。缺失或 <32 字节 → RuntimeError。

    fail-closed：凭证端点才触发，不影响非凭证功能（技能目录/选购照常）。
    """
    raw = os.getenv("STORE_MASTER_KEY", "").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        key = b""
    if len(key) < 32:
        raise RuntimeError(
            "STORE_MASTER_KEY 未配置或格式错误：需 32 字节 hex（64 位十六进制）。"
            '生成：python -c "import secrets;print(secrets.token_hex(32))"'
        )
    return key


def _aad(user_id: str, skill_id: str) -> bytes:
    """AAD = user_id:skill_id：密文绑定属主，防跨用户/跨技能互换（§13 权限隔离）。"""
    return f"{user_id}:{skill_id}".encode("utf-8")


def _encrypt(user_id: str, skill_id: str, values: dict) -> str:
    """凭证 dict → AES-256-GCM 密文（base64(nonce + ct+tag)，nonce 12 字节随机）。"""
    nonce = os.urandom(12)
    plain = json.dumps(values, ensure_ascii=False).encode("utf-8")
    ct = AESGCM(_master_key()).encrypt(nonce, plain, _aad(user_id, skill_id))
    return base64.b64encode(nonce + ct).decode("ascii")


def _decrypt(user_id: str, skill_id: str, blob: str) -> dict:
    """密文 → 凭证 dict。AAD 不匹配/被篡改/密钥不符 → 抛清晰错误（不裸抛 InvalidTag）。"""
    try:
        raw = base64.b64decode(blob.encode("ascii"))
        nonce, ct = raw[:12], raw[12:]
        plain = AESGCM(_master_key()).decrypt(nonce, ct, _aad(user_id, skill_id))
        return json.loads(plain.decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"凭证解密失败（{type(e).__name__}）") from e


def put_credentials(conn: sqlite3.Connection, user_id: str, skill_id: str, values: dict) -> int:
    """保存凭证（UPSERT）+ version+1。凭证改连接参数 → bump 版本让 server 重建带新凭证的连接。"""
    blob = _encrypt(user_id, skill_id, values)
    conn.execute(
        """INSERT INTO user_skill_credentials (user_id, skill_id, cred_json, updated_at)
           VALUES (?,?,?,datetime('now'))
           ON CONFLICT(user_id, skill_id) DO UPDATE SET
             cred_json=excluded.cred_json, updated_at=datetime('now')""",
        (user_id, skill_id, blob),
    )
    return _bump_version(conn, user_id)


def get_credentials(conn: sqlite3.Connection, user_id: str, skill_id: str) -> dict | None:
    """明文凭证（server_py 内部用，GET /me/credentials/plain）。无记录 → None。"""
    row = conn.execute(
        "SELECT cred_json FROM user_skill_credentials WHERE user_id=? AND skill_id=?",
        (user_id, skill_id),
    ).fetchone()
    return _decrypt(user_id, skill_id, row["cred_json"]) if row else None


def get_credentials_masked(
    conn: sqlite3.Connection, user_id: str, skill_id: str, schema: list | None
) -> dict:
    """脱敏凭证（web/App 用，GET /me/credentials）：secret/textarea/file 字段值置 None，
    其余（string/number/boolean/select）返回明文供表单预填。始终返回 {configured, values}。"""
    if schema is None:
        schema = []
    secret_types = {"secret", "textarea", "file"}
    values = get_credentials(conn, user_id, skill_id) or {}
    masked = {
        f["key"]: (None if f.get("type") in secret_types else values.get(f["key"]))
        for f in schema
    }
    return {"configured": bool(values), "values": masked}


def delete_credentials(conn: sqlite3.Connection, user_id: str, skill_id: str) -> int:
    """删除凭证 + version+1（让 server 重连无凭证连接）。删成功才 bump。"""
    cur = conn.execute(
        "DELETE FROM user_skill_credentials WHERE user_id=? AND skill_id=?",
        (user_id, skill_id),
    )
    if cur.rowcount == 0:
        return _current_version(conn, user_id)
    return _bump_version(conn, user_id)
