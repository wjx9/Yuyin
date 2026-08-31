"""技能商店后端（P2）：独立于 server_py，FastAPI + SQLite。

端口约定：商店 9000；mock MCP 9100；主服务 serve.py 8000。
数据流：web 选购页 PUT /me/skills → version+1 → server_py GET /me/skills/sync 拉取。
"""
