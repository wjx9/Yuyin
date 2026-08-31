"""预置技能入口（兼容保留）：现已改为官方 MCP 目录同步。

预置技能（weather-mcp / stock-mcp / region-mcp / mcdonalds-mcp / eastmoney-mcp）已迁入
connectors/*.json 声明式目录，由 catalog.sync_catalog() 幂等同步进库（启动时自动跑，
也可手动 `POST /skills/catalog/sync`）。本文件只留手动命令兼容入口：
    .venv\\Scripts\\python -m skill_store.seed
"""

from . import catalog


def seed() -> None:
    catalog.sync_catalog()


if __name__ == "__main__":
    seed()
