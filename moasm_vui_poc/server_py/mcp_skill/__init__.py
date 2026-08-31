"""mcp_skill：统一远程 MCP 与内置能力的 Handler 适配层。

- manifest.py    SkillManifest 模型 + manifest→SlotSpec 映射
- client.py      McpToolClient（远程）+ LocalHandlerClient（内置 local transport）
- handler.py     MCPHandler(Handler)：技能入口
- assembly.py    本地装配入口：读本地 manifest JSON → MCPHandler 列表（P2 换商店 sync）
"""
