from mcp_skill.client import LocalHandlerClient
from mcp_skill.handler import MCPHandler
from mcp_skill.manifest import SkillManifest
from routing.handler import Handler, RouteContext, RouteResult, SlotSpec


class _EchoHandler(Handler):
    intent = "echo_local"
    description = "本地测试能力"
    slots = (SlotSpec("text", "string", "文本", required=True),)

    def handle(self, query, context):
        return RouteResult(
            text=f"echo:{query}:{context.slots.get('text')}",
            data={"transport": "local"},
            intent=self.intent,
            source="echo",
        )


def test_local_handler_can_use_the_same_mcp_handler_contract():
    manifest = SkillManifest.from_dict(
        {
            "skill_id": "builtin:echo_local",
            "name": "本地测试能力",
            "description": "本地测试能力",
            "intent": "echo_local",
            "entry_tool": "echo_local",
            "mcp_server": {"transport": "local", "url": "handler://echo_local"},
            "tools": [
                {
                    "name": "echo_local",
                    "input_schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }
            ],
            "kind": "builtin",
        }
    )
    result = MCPHandler(manifest, LocalHandlerClient(_EchoHandler())).handle(
        "原始问题", RouteContext(slots={"text": "参数"})
    )
    assert result.text == "echo:原始问题:参数"
    assert result.data == {"transport": "local"}
    assert result.method == "mcp"

