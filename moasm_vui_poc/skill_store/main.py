"""技能商店后端（P2）—— FastAPI 应用（设计 最终技术路线.md §5.2 + 动态凭证系统 §7）。

接口：
  GET  /skills              目录（active 技能 + 完整 manifest）
  POST /skills              上架（intent 唯一性校验，冲突 409）
  PUT  /skills/{id}/status  任意技能上架/下架
  POST /skills/sync-all     同步内置能力与远程 MCP 目录
  GET  /me/skills?user_id=  用户选购的 skill_id 列表 + enabled 状态
  PUT  /me/skills           {user_id, skill_ids} 保存选购，写后 version+1
  PUT  /me/skills/enabled   {user_id, skill_id, enabled} 单技能启/停（开启自动选购）
  PUT  /me/skills/remove    {user_id, skill_id} 退订（级联删凭证）
  GET  /me/skills/sync?user_id=  {version, skills} —— server_py 拉取入口
  GET  /me/credentials?user_id=&skill_id=        凭证状态（脱敏，web/App 用）
  GET  /me/credentials/plain?user_id=&skill_id=  凭证明文（server_py 专用）
  PUT  /me/credentials      {user_id, skill_id, values} 保存凭证（AES-GCM 加密），写后 version+1
  DELETE /me/credentials?user_id=&skill_id=      删除凭证，删后 version+1
  GET  /                     web 选购页

POC 不鉴权：user_id 由客户端传（商用接真实账号体系，见 设计 §9-7）。
启动（仓库根）：.venv\\Scripts\\python -m uvicorn skill_store.main:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import builtin_catalog, catalog, db, mcp_probe


def _load_env() -> None:
    """加载仓库根 .env（STORE_MASTER_KEY 等），与 server_py/serve.py 一致。

    商店直跑 uvicorn 不自动读 .env，缺这一步按文档启动时会因拿不到主密钥
    在写凭证时 fail-closed 500。缺 dotenv 时静默跳过（测试环境不强制）。
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except ImportError:
        return


_load_env()

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# 内置意图集（与 server_py/orchestration/factory.py 的 _PLANNABLE_INTENTS 同步）：
# 撞内置的 intent 在 server 侧会被冲突过滤静默跳过，管理员上架时应直接 409 拦下。
# 改动 server 侧内置意图时，记得同步这里。
_BUILTIN_INTENTS = {
    "chitchat",
    "calendar_create",
    "alarm_create",
    "timer_create",
    "reminder_create",
    "amap",
    "amap_geocode",
    "amap_regeo",
    "amap_weather_live",
    "amap_weather_forecast",
    "amap_driving",
    "amap_walking",
    "amap_bicycling",
    "amap_transit",
    "exa_search",
    "tencent_hot_news",
    "tencent_news_search",
    "tripnow_public",
    "tripnow_personal",
    "express_tracking",
    "music_play",
    "music_control",
}


def _credentials_schema(conn, skill_id: str) -> list | None:
    """技能 manifest 里的 credentials.schema（凭证字段定义）。技能不存在 → None。"""
    row = conn.execute("SELECT manifest FROM skills WHERE skill_id=?", (skill_id,)).fetchone()
    if not row:
        return None
    creds = json.loads(row["manifest"]).get("credentials") or {}
    return creds.get("schema") or []


def _get_skill_manifest(conn, skill_id: str) -> dict | None:
    """技能完整 manifest。不存在 → None。"""
    row = conn.execute("SELECT manifest FROM skills WHERE skill_id=?", (skill_id,)).fetchone()
    return json.loads(row["manifest"]) if row else None


def _schema_signature(schema: list) -> list:
    """提取 schema 的关键签名（用于凭证复用判断）。

    只比较影响凭证注入的字段：key、type、required、inject。
    忽略 label、help、placeholder 等纯展示字段（不同技能的文案可能不同，但注入方式相同）。
    """
    sig = []
    for f in schema or []:
        sig.append({
            "key": f.get("key"),
            "type": f.get("type"),
            "required": f.get("required", False),
            "inject": f.get("inject"),
        })
    return sig


def _find_reusable_credentials(conn, user_id: str, target_skill_id: str) -> dict | None:
    """查找可复用的凭证：同用户、同 mcp_server.url、同凭证 schema 签名的已配置技能。

    返回 {from_skill_id, values} 或 None（无可复用）。
    复用条件：
      - 目标技能是 byok 类型（需要凭证）
      - 目标技能尚未配置凭证
      - 存在另一个已配置凭证的技能，其 mcp_server.url 和凭证 schema 签名与目标相同
    """
    target = _get_skill_manifest(conn, target_skill_id)
    if target is None:
        return None
    target_creds = target.get("credentials") or {}
    if target_creds.get("type") != "byok":
        return None  # 非 byok 技能不需要凭证
    target_url = (target.get("mcp_server") or {}).get("url", "")
    target_sig = _schema_signature(target_creds.get("schema") or [])

    # 目标技能已配置凭证 → 不需要复用
    existing = db.get_credentials(conn, user_id, target_skill_id)
    if existing:
        return None

    # 查询该用户所有已配置凭证的技能（排除目标）
    rows = conn.execute(
        """SELECT c.skill_id
           FROM user_skill_credentials c
           WHERE c.user_id=? AND c.skill_id != ?""",
        (user_id, target_skill_id),
    ).fetchall()

    for r in rows:
        other_manifest = _get_skill_manifest(conn, r["skill_id"])
        if other_manifest is None:
            continue
        other_creds = other_manifest.get("credentials") or {}
        if other_creds.get("type") != "byok":
            continue
        other_url = (other_manifest.get("mcp_server") or {}).get("url", "")
        other_sig = _schema_signature(other_creds.get("schema") or [])
        # 同 URL + 同 schema 签名 → 可复用
        if other_url == target_url and other_sig == target_sig:
            values = db.get_credentials(conn, user_id, r["skill_id"])
            if values:
                return {"from_skill_id": r["skill_id"], "values": values}
    return None


def _skill_status(conn, skill_id: str) -> str | None:
    """技能上下架状态（管理员轴）。None=不存在，'active'|'inactive'。

    管理员/用户状态隔离的判定依据：用户只能「新建启用/配置」上架中的技能；
    已下架技能的用户行（选购+启用）由管理员动作保留，不作为可新建的目标。
    """
    row = conn.execute("SELECT status FROM skills WHERE skill_id=?", (skill_id,)).fetchone()
    return row["status"] if row else None


def _bump_skill_holders(conn, skill_id: str) -> int:
    """技能发布/更新/下架/删除后，给所有持有者 version+1（让 server 侧重建图）。返回受影响人数。

    同一事务内调用：与写操作原子，避免"改了 manifest 但 version 没变"导致用户图不刷新。
    """
    rows = conn.execute(
        "SELECT user_id FROM user_skills WHERE skill_id=?", (skill_id,)
    ).fetchall()
    for r in rows:
        conn.execute(
            """INSERT INTO user_skill_versions (user_id, version) VALUES (?,1)
               ON CONFLICT(user_id) DO UPDATE SET version = version + 1""",
            (r["user_id"],),
        )
    return len(rows)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()  # 幂等：启动即建表
    catalog.sync_catalog()  # 官方 MCP 目录：connectors/*.json 幂等同步进库（管理员只管上架/下架）
    builtin_catalog.sync_catalog()  # 内置 Handler 也进入同一目录，避免直跑 9000 时缺失
    yield


app = FastAPI(title="技能商店", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # POC：web 页直连；商用收紧
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RuntimeError)
def _on_runtime_error(request, exc: RuntimeError) -> JSONResponse:
    """凭证加解密等内部失败 → 干净 500（带原因），不把 traceback 漏给前端（§13 日志脱敏）。"""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/skills")
def list_skills() -> dict:
    """目录：active 技能 + 完整 manifest（assistant 服务不代理、不缓存目录，见 §4.5）。"""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT manifest FROM skills WHERE status='active' ORDER BY updated_at"
        ).fetchall()
    return {"skills": [json.loads(r["manifest"]) for r in rows]}


@app.post("/internal/builtin-skills/sync")
def sync_builtin_skills(body: dict) -> dict:
    """由主服务同步当前实际注册的内置能力；内置能力不需要 MCP 连接。"""
    skills = body.get("skills")
    if not isinstance(skills, list):
        raise HTTPException(400, "skills 必须是数组")
    synced = []
    with db.connect() as conn:
        for manifest in skills:
            if not isinstance(manifest, dict) or manifest.get("kind") != "builtin":
                raise HTTPException(400, "只允许同步 kind=builtin 的 manifest")
            required = ("skill_id", "name", "intent")
            if any(not manifest.get(k) for k in required):
                raise HTTPException(400, "内置 manifest 缺少 skill_id/name/intent")
            raw = json.dumps(manifest, ensure_ascii=False)
            conn.execute(
                """INSERT INTO skills
                   (skill_id,name,description,icon,intent,manifest,publisher,status,updated_at)
                   VALUES (?,?,?,?,?,?,?, 'active', datetime('now'))
                   ON CONFLICT(skill_id) DO UPDATE SET
                     name=excluded.name, description=excluded.description, icon=excluded.icon,
                     intent=excluded.intent, manifest=excluded.manifest,
                     publisher='builtin', updated_at=datetime('now')""",
                (manifest["skill_id"], manifest["name"], manifest.get("description", ""),
                 manifest.get("icon", ""), manifest["intent"], raw, "builtin"),
            )
            synced.append(manifest["skill_id"])
    return {"ok": True, "synced": synced}


@app.post("/skills")
def publish(body: dict) -> dict:
    """上架/更新（管理员）。intent 唯一性（设计 §2.2①）+ 撞内置 409。

    支持 status：active（默认）| inactive（下架）。下架技能不在目录/用户 sync 里出现，
    但保留在 skills 表（可重新上架）。发布/更新/下架后给持有者 bump 版本，热插拔生效。
    """
    manifest = body["manifest"]
    status = body.get("status", "active")
    if status not in ("active", "inactive"):
        raise HTTPException(400, f"status 只能是 active|inactive，收到 {status!r}")
    if manifest.get("intent") in _BUILTIN_INTENTS:
        raise HTTPException(
            409,
            f"intent {manifest['intent']!r} 是内置能力，不能作为 MCP 技能 intent（会撞 dispatcher）",
        )
    with db.connect() as conn:
        dup = conn.execute(
            "SELECT skill_id FROM skills WHERE intent=? AND skill_id!=? AND status='active'",
            (manifest["intent"], manifest["skill_id"]),
        ).fetchone()
        if dup:
            raise HTTPException(409, f"intent {manifest['intent']!r} 已被技能 {dup['skill_id']} 占用")
        conn.execute(
            """INSERT INTO skills (skill_id,name,description,icon,intent,manifest,publisher,status,updated_at)
               VALUES (?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(skill_id) DO UPDATE SET
                 name=excluded.name, description=excluded.description, icon=excluded.icon,
                 intent=excluded.intent, manifest=excluded.manifest, publisher=excluded.publisher,
                 status=excluded.status, updated_at=datetime('now')""",
            (
                manifest["skill_id"],
                manifest["name"],
                manifest.get("description", ""),
                manifest.get("icon", ""),
                manifest["intent"],
                json.dumps(manifest, ensure_ascii=False),
                body.get("publisher", "poc"),
                status,
            ),
        )
        bumped = _bump_skill_holders(conn, manifest["skill_id"])
    return {"ok": True, "skill_id": manifest["skill_id"], "status": status, "holders_bumped": bumped}


@app.post("/skills/probe")
def probe_tools(body: dict) -> dict:
    """豆包「连接器」式工具发现：填 MCP server 地址 → list_tools 返回可用工具。

    P4.3：可选 probe_headers（{header名: 值}，如 {"Authorization": "Bearer <临时Token>"}），
    给需要鉴权的官方 MCP（麦当劳等，连握手都要 Bearer）probe 用——临时 Token 只在这次
    请求里用，不入库、不进 manifest。超时 30s（真实麦当劳 list_tools 枚举 30 工具实测 ~18s）。

    必须同步 def：FastAPI 丢线程池跑（asyncio.run 安全）；async def 里 asyncio.run 会 RuntimeError。
    失败不抛 5xx，返回 {ok:false, error}，让前端展示"连接失败"而不是红屏。
    """
    mcp_server = body.get("mcp_server")
    transport = body.get("transport", "http")
    if transport != "http":
        raise HTTPException(400, f"暂只支持 HTTP/SSE 远程 MCP（transport='http'），收到 {transport!r}")
    if not isinstance(mcp_server, str) or not mcp_server.strip():
        raise HTTPException(400, "mcp_server 必须是 MCP server 地址，如 http://127.0.0.1:9100/mcp")
    probe_headers = body.get("probe_headers") or {}
    if not isinstance(probe_headers, dict):
        raise HTTPException(400, "probe_headers 必须是对象 {header名: 值}")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in probe_headers.items()):
        raise HTTPException(400, "probe_headers 的键和值都必须是字符串")
    url = mcp_server.strip()
    try:
        tools = mcp_probe.list_tools(url, timeout=30.0, headers=probe_headers or None)
    except mcp_probe.ProbeError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "mcp_server": url, "tools": tools}


@app.post("/skills/catalog/sync")
def sync_catalog_endpoint() -> dict:
    """重跑官方 MCP 目录同步（管理员改 connectors/*.json 后免重启商店生效）。"""
    result = catalog.sync_catalog()
    return {"ok": True, **result}


@app.post("/skills/sync-all")
def sync_all_endpoint() -> dict:
    """同步统一技能目录：远程 MCP connector + 当前可用的内置 Handler。"""
    remote = catalog.sync_catalog()
    builtin = builtin_catalog.sync_catalog()
    return {
        "ok": True,
        "synced": remote.get("synced", []) + builtin.get("synced", []),
        "bumped": remote.get("bumped", 0),
        "builtin_count": builtin.get("count", 0),
    }


@app.get("/skills/admin")
def admin_skills() -> dict:
    """管理员视角：全部技能（含已下架 inactive）+ 状态。"""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT skill_id, name, description, icon, intent, status, publisher, updated_at
               FROM skills ORDER BY updated_at"""
        ).fetchall()
    return {"skills": [dict(r) for r in rows]}


@app.put("/skills/{skill_id}/status")
def set_skill_status(skill_id: str, body: dict) -> dict:
    """统一修改任意技能的上架状态（内置、远程和自定义技能都适用）。"""
    status = body.get("status")
    if status not in ("active", "inactive"):
        raise HTTPException(400, "status 只能是 active|inactive")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status FROM skills WHERE skill_id=?", (skill_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"技能 {skill_id!r} 不存在")
        if row["status"] == status:
            bumped = 0
        else:
            conn.execute(
                "UPDATE skills SET status=?, updated_at=datetime('now') WHERE skill_id=?",
                (status, skill_id),
            )
            bumped = _bump_skill_holders(conn, skill_id)
    return {"ok": True, "skill_id": skill_id, "status": status, "holders_bumped": bumped}


@app.get("/skills/{skill_id}")
def get_skill(skill_id: str) -> dict:
    """取单个技能的完整 manifest + 状态（管理员改状态/编辑用）。"""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT manifest, status FROM skills WHERE skill_id=?", (skill_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"技能 {skill_id!r} 不存在")
    return {"skill_id": skill_id, "status": row["status"], "manifest": json.loads(row["manifest"])}


@app.delete("/skills/{skill_id}")
def delete_skill(skill_id: str) -> dict:
    """删除技能（硬删）：级联清 user_skills + user_skill_credentials + 给持有者 bump 版本；不存在 404。"""
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM skills WHERE skill_id=?", (skill_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"技能 {skill_id!r} 不存在")
        holders = _bump_skill_holders(conn, skill_id)
        conn.execute("DELETE FROM user_skills WHERE skill_id=?", (skill_id,))
        conn.execute("DELETE FROM user_skill_credentials WHERE skill_id=?", (skill_id,))
        conn.execute("DELETE FROM skills WHERE skill_id=?", (skill_id,))
    return {"ok": True, "skill_id": skill_id, "holders_bumped": holders}


@app.get("/me/skills")
def me(user_id: str) -> dict:
    """用户选购的 skill_id 列表 + 每个技能的启用状态（enabled: {skill_id: bool}）。

    skill_ids 保留（PC web 只读它）；enabled 只含已选购的技能（区分"已选购"与"已启用"）。
    """
    with db.connect() as conn:
        rows = conn.execute("SELECT skill_id, enabled FROM user_skills WHERE user_id=?", (user_id,)).fetchall()
        builtin_rows = conn.execute(
            "SELECT skill_id, manifest FROM skills WHERE status='active' AND publisher='builtin'"
        ).fetchall()
    overrides = {r["skill_id"]: bool(r["enabled"]) for r in rows}
    for r in builtin_rows:
        manifest = json.loads(r["manifest"])
        overrides.setdefault(r["skill_id"], bool(manifest.get("always_enabled", True)))
    return {
        "user_id": user_id,
        "skill_ids": list(overrides),
        "enabled": overrides,
    }


@app.get("/me/skills/detail")
def me_detail(user_id: str) -> dict:
    """用户已选购的技能（**含已下架**）：渲染字段 + status + enabled + credentials。

    管理员下架的技能不在目录（GET /skills）里、也不进 sync，但用户的选购/启用行被保留
    （状态隔离语义）。本端点让 web/手机端能渲染「已下架」卡，用户在下架期间仍可停用/退订。
    只含已选购（JOIN user_skills）；未选购技能不出现。
    """
    with db.connect() as conn:
        ver_row = conn.execute(
            "SELECT version FROM user_skill_versions WHERE user_id=?", (user_id,)
        ).fetchone()
        version = int(ver_row["version"]) if ver_row else 0
        rows = conn.execute(
            """SELECT m.manifest, m.status, u.enabled
               FROM skills m JOIN user_skills u ON u.skill_id = m.skill_id
               WHERE u.user_id=?""",
            (user_id,),
        ).fetchall()
    skills = []
    seen = set()
    for r in rows:
        man = json.loads(r["manifest"])
        seen.add(man["skill_id"])
        skills.append(
            {
                "skill_id": man["skill_id"],
                "name": man.get("name", ""),
                "icon": man.get("icon", ""),
                "description": man.get("description", ""),
                "credentials": man.get("credentials"),
                "status": r["status"],
                "enabled": bool(r["enabled"]),
                "kind": man.get("kind", "mcp"),
            }
        )
    with db.connect() as conn:
        builtin_rows = conn.execute(
            "SELECT manifest FROM skills WHERE status='active' AND publisher='builtin'"
        ).fetchall()
    for r in builtin_rows:
        man = json.loads(r["manifest"])
        if man["skill_id"] in seen:
            continue
        skills.append({
            "skill_id": man["skill_id"], "name": man.get("name", ""),
            "icon": man.get("icon", ""), "description": man.get("description", ""),
            "credentials": man.get("credentials"), "status": "active",
            "enabled": bool(man.get("always_enabled", True)), "kind": "builtin",
        })
    return {"user_id": user_id, "version": version, "skills": skills}


@app.put("/me/skills")
def put_me(body: dict) -> dict:
    """保存选购（全量替换，全部启用）；写后 version+1（同一事务，§5.2）。"""
    user_id = body["user_id"]
    skill_ids = body["skill_ids"]
    if not isinstance(skill_ids, list):
        raise HTTPException(400, "skill_ids 必须是数组")
    with db.connect() as conn:
        version = db.put_user_skills(conn, user_id, skill_ids)
    return {"user_id": user_id, "version": version}


@app.put("/me/skills/enabled")
def set_enabled(body: dict) -> dict:
    """单技能启用/停用。未选购时置 enabled=true 即自动选购；停用保留选购。写后 version+1。

    状态隔离：启用是「新建启用」——只能对管理员已上架（active）的技能；下架/不存在 → 409/404。
    停用保留清理权，不设限（用户对自己任何已购行都能停用）。
    """
    user_id = body["user_id"]
    skill_id = body["skill_id"]
    if not isinstance(skill_id, str) or not skill_id:
        raise HTTPException(400, "skill_id 必须是字符串")
    if not isinstance(body.get("enabled"), bool):
        raise HTTPException(400, "enabled 必须是布尔")
    with db.connect() as conn:
        if body["enabled"]:
            status = _skill_status(conn, skill_id)
            if status is None:
                raise HTTPException(404, f"技能 {skill_id!r} 不存在")
            if status != "active":
                raise HTTPException(409, f"技能 {skill_id!r} 已下架，无法启用")
        version = db.set_skill_enabled(conn, user_id, skill_id, body["enabled"])
        # 凭证自动复用：启用 byok 技能时，若用户已为同 MCP server + 同 schema 的其他技能配置过凭证，
        # 自动复制过来，无需用户重复填写。复用成功不额外 bump（set_skill_enabled 已 bump）。
        reused = None
        if body["enabled"]:
            reused = _find_reusable_credentials(conn, user_id, skill_id)
            if reused:
                db.put_credentials(conn, user_id, skill_id, reused["values"])
    result = {"user_id": user_id, "version": version}
    if reused:
        result["credentials_reused"] = True
        result["reused_from"] = reused["from_skill_id"]
    return result


@app.put("/me/skills/remove")
def remove_me(body: dict) -> dict:
    """退订：移除选购（级联删凭证，见三态语义：退订才移除，停用保留）。删成功 version+1。"""
    user_id = body["user_id"]
    skill_id = body["skill_id"]
    if not isinstance(skill_id, str) or not skill_id:
        raise HTTPException(400, "skill_id 必须是字符串")
    with db.connect() as conn:
        version = db.remove_skill(conn, user_id, skill_id)
    return {"user_id": user_id, "version": version}


@app.get("/me/credentials")
def get_credentials(user_id: str, skill_id: str) -> dict:
    """凭证状态（脱敏，web/App 用）：secret/textarea/file 字段不返回明文，其余返回供表单预填。

    技能不存在 → 404；始终返回 {configured, values}，不因无记录而 404（前端好判断）。
    """
    with db.connect() as conn:
        schema = _credentials_schema(conn, skill_id)
        if schema is None:
            raise HTTPException(404, f"技能 {skill_id!r} 不存在")
        return db.get_credentials_masked(conn, user_id, skill_id, schema)


@app.get("/me/credentials/plain")
def get_credentials_plain(user_id: str, skill_id: str) -> dict:
    """凭证明文（server_py StoreClient 专用，供连接注入）。POC 无鉴权，商用需加鉴权/HTTPS（§13）。"""
    with db.connect() as conn:
        values = db.get_credentials(conn, user_id, skill_id)
    return {
        "user_id": user_id,
        "skill_id": skill_id,
        "configured": bool(values),
        "values": values or {},
    }


@app.put("/me/credentials")
def put_credentials(body: dict) -> dict:
    """保存凭证：校验技能存在且上架 + 必填字段齐 → AES-GCM 加密存储 + version+1（server 重建带新凭证连接）。

    状态隔离：给下架技能新建/更新凭证是死状态 → 409（管理员下架期间不产生新凭证）；清凭证不限（清理权）。
    """
    user_id = body["user_id"]
    skill_id = body["skill_id"]
    values = body.get("values")
    if not isinstance(skill_id, str) or not skill_id:
        raise HTTPException(400, "skill_id 必须是字符串")
    if not isinstance(values, dict):
        raise HTTPException(400, "values 必须是对象")
    with db.connect() as conn:
        status = _skill_status(conn, skill_id)
        if status is None:
            raise HTTPException(404, f"技能 {skill_id!r} 不存在")
        if status != "active":
            raise HTTPException(409, f"技能 {skill_id!r} 已下架，无法配置凭证")
        schema = _credentials_schema(conn, skill_id)
        if schema is None:
            raise HTTPException(404, f"技能 {skill_id!r} 不存在")
        existing = db.get_credentials(conn, user_id, skill_id) or {}
        merged = dict(existing)
        for f in schema:
            key = f["key"]
            if key not in values:
                continue  # 未提交的字段不碰
            v = values[key]
            # 敏感字段（secret/textarea/file）留空 = 保留旧值：脱敏 GET 不回传明文，
            # 前端无法预填，用户"只改非敏感字段"保存时不能把已存密钥清空。
            if v in (None, "") and key in existing and f.get("type") in ("secret", "textarea", "file"):
                continue
            merged[key] = v
        for f in schema:
            key = f["key"]
            if f.get("required") and (key not in merged or merged[key] in (None, "")):
                raise HTTPException(400, f"缺少必填凭证字段：{f.get('label', key)}")
        version = db.put_credentials(conn, user_id, skill_id, merged)
    return {"user_id": user_id, "skill_id": skill_id, "version": version}


@app.delete("/me/credentials")
def delete_credentials(user_id: str, skill_id: str) -> dict:
    """删除凭证 + version+1（server 重建无凭证连接）。删不存在返回当前版本。"""
    with db.connect() as conn:
        version = db.delete_credentials(conn, user_id, skill_id)
    return {"user_id": user_id, "skill_id": skill_id, "version": version}


@app.get("/me/skills/sync")
def sync(user_id: str) -> dict:
    """server_py 拉取入口：版本 + 该用户**已启用**的完整 manifest 列表。

    enabled=0（已选购但停用）的技能不进数组 → server 侧重建图时断开 MCP 连接并移除路由
    （配合版本 +1，见 server/service.py 的严格递增重建）。
    """
    with db.connect() as conn:
        ver_row = conn.execute(
            "SELECT version FROM user_skill_versions WHERE user_id=?", (user_id,)
        ).fetchone()
        version = int(ver_row["version"]) if ver_row else 0
        rows = conn.execute(
            """SELECT m.manifest FROM skills m
               JOIN user_skills u ON u.skill_id = m.skill_id
               WHERE u.user_id=? AND u.enabled=1 AND m.status='active'""",
            (user_id,),
        ).fetchall()
        builtin_rows = conn.execute(
            "SELECT skill_id, manifest FROM skills WHERE status='active' AND publisher='builtin'"
        ).fetchall()
        disabled = {
            r["skill_id"] for r in conn.execute(
                "SELECT skill_id FROM user_skills WHERE user_id=? AND enabled=0", (user_id,)
            ).fetchall()
        }
    manifests = [json.loads(r["manifest"]) for r in rows]
    manifests.extend(
        json.loads(r["manifest"])
        for r in builtin_rows
        if r["skill_id"] not in disabled
    )
    return {
        "user_id": user_id,
        "version": version,
        "skills": manifests,
    }
