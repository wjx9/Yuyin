"""官方 MCP 目录（connector catalog）：仓库内置 connectors/*.json → skills 表幂等同步。

模型（用户 2026-08-28 拍板）：管理员只负责上架/下架；加官方 MCP = 往 connectors/ 放一个
JSON（走开发/评审），不用 probe → 手拼 manifest。publisher='catalog' 标记目录技能，
管理页按此分组「官方目录」vs「自定义 MCP」。

同步语义：
  - 新 connector 落库取 default_status（缺省 'inactive'，即「待上架」）；
  - 已有行 status 不被触碰（保留管理员当前上架/下架）；
  - 仅 manifest 或 publisher 变化才写库；仅 manifest 变化才 bump 持有者（server ≤30s 重建图）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import db

_log = logging.getLogger("skill_store.catalog")

CONNECTORS_DIR = Path(__file__).resolve().parent / "connectors"

# 目录 connector 的 publisher 标记（管理页分组依据，见 skill_store/static/index.html）
CATALOG_PUBLISHER = "catalog"

_SKILL_COLS = (
    "skill_id,name,description,icon,intent,manifest,publisher,status,updated_at"
)


def _bump_skill_holders(conn, skill_id: str) -> int:
    """manifest 变更 → 给所有已选购该技能的用户 bump 版本（热插拔生效）。返回持有者数。"""
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


def _load_connectors(dir_path: Path) -> list[dict]:
    """读 connectors/*.json：每文件 = 完整 manifest + 可选 default_status（缺省 'inactive'）。"""
    result: list[dict] = []
    if not dir_path.is_dir():
        _log.warning("connectors 目录不存在：%s", dir_path)
        return result
    for p in sorted(dir_path.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            _log.warning("跳过坏 connector %s：%s", p.name, e)
            continue
        manifest = {k: v for k, v in data.items() if k != "default_status"}
        if not manifest.get("skill_id") or not manifest.get("intent"):
            _log.warning("跳过缺 skill_id/intent 的 connector：%s", p.name)
            continue
        result.append(
            {"manifest": manifest, "default_status": data.get("default_status", "inactive")}
        )
    return result


def sync_catalog(dir_path: Path | None = None) -> dict:
    """幂等同步 connectors/*.json → skills 表。返回 {synced: [skill_id], bumped: int}。

    dir_path 参数化便于测试（传临时目录）；默认仓库 connectors/。
    """
    dir_path = dir_path or CONNECTORS_DIR
    synced: list[str] = []
    bumped = 0
    with db.connect() as conn:
        for c in _load_connectors(dir_path):
            m = c["manifest"]
            new_manifest = json.dumps(m, ensure_ascii=False)
            existing = conn.execute(
                "SELECT manifest, publisher FROM skills WHERE skill_id=?", (m["skill_id"],)
            ).fetchone()
            manifest_changed = existing is None or existing["manifest"] != new_manifest
            needs_write = manifest_changed or (
                existing is not None and existing["publisher"] != CATALOG_PUBLISHER
            )
            if not needs_write:
                continue  # 未变化：不重复写、不 bump
            conn.execute(
                f"""INSERT INTO skills ({_SKILL_COLS}) VALUES (?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(skill_id) DO UPDATE SET
                      name=excluded.name, description=excluded.description, icon=excluded.icon,
                      intent=excluded.intent, manifest=excluded.manifest,
                      publisher=excluded.publisher, updated_at=datetime('now')""",
                (
                    m["skill_id"],
                    m["name"],
                    m.get("description", ""),
                    m.get("icon", ""),
                    m["intent"],
                    new_manifest,
                    CATALOG_PUBLISHER,
                    c["default_status"],  # 仅 INSERT（新行）生效；DO UPDATE 不碰 status
                ),
            )
            if manifest_changed:
                bumped += _bump_skill_holders(conn, m["skill_id"])
            synced.append(m["skill_id"])
    _log.info("目录同步完成：synced=%s bumped=%s", synced, bumped)
    return {"synced": synced, "bumped": bumped}
