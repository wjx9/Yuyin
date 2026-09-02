"""SQLite 表结构（设计 最终技术路线.md §5.1 + 动态凭证系统 §7）。

四张表：
  skills                    —— 技能目录（完整 manifest JSON 存 manifest 列）
  user_skills               —— 用户选购关系（enabled 列：1=启用，0=已选购但停用）
  user_skill_versions       —— 每用户版本号（选购变更时同事务 +1）
  user_skill_credentials    —— 用户凭证（AES-256-GCM 加密后的 JSON）

version 用独立表而非 MAX(updated_at)：并发/同秒写入会撞值，无法可靠判变更（§5.2）。
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
  skill_id   TEXT PRIMARY KEY,
  name       TEXT,
  description TEXT,
  icon       TEXT,
  intent     TEXT,
  manifest   TEXT,           -- 完整 manifest JSON（含 mcp_server / tools）
  publisher  TEXT,
  status     TEXT DEFAULT 'active',   -- active | inactive
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS user_skills (
  user_id    TEXT,
  skill_id   TEXT,
  enabled_at TEXT,
  PRIMARY KEY (user_id, skill_id)
);

CREATE TABLE IF NOT EXISTS user_skill_versions (
  user_id  TEXT PRIMARY KEY,
  version  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_skill_credentials (
  user_id    TEXT,
  skill_id   TEXT,
  cred_json  TEXT,           -- AES-256-GCM 加密后的凭证 JSON
  updated_at TEXT,
  PRIMARY KEY (user_id, skill_id)
);
"""
