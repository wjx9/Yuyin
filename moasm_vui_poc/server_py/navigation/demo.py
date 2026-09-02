"""导航对话引擎交互式 Demo。

用法：
    python -m server_py.navigation.demo              # 使用真实高德API（需AMAP_KEY）
    python -m server_py.navigation.demo --mock       # 使用mock数据（无需API Key）
    python -m server_py.navigation.demo --scenario 1 # 自动演示场景1

交互命令：
    直接输入用户指令（如"导航到大新"）
    status    - 查看当前状态
    reset     - 重置引擎
    scenario N - 演示场景N（1-5）
    help      - 显示帮助
    quit/exit - 退出
"""

from __future__ import annotations

import argparse
import os
import sys

# 确保可以导入server_py模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from navigation import (
    Controller,
    NavState,
    NavigationEngine,
    NavigationService,
    Poi,
    PoiSearchService,
)


# ── Mock 数据 ─────────────────────────────────────────────────

MOCK_POIS = {
    "大新": [
        Poi(name="大新地铁站", address="深圳市南山区大新地铁站", location="113.93,22.57", distance_m=500),
        Poi(name="大新公园", address="深圳市南山区大新公园", location="113.94,22.58", distance_m=800),
        Poi(name="大新地铁站B口", address="深圳市南山区大新地铁站B口", location="113.93,22.57", distance_m=520),
    ],
    "深圳湾公园": [
        Poi(name="深圳湾公园", address="深圳市南山区深圳湾公园", location="113.95,22.52", distance_m=2000),
    ],
    "公司": [
        Poi(name="雷鸟创新科技有限公司", address="深圳市南山区科技园", location="113.95,22.55", distance_m=3000),
    ],
    "家": [
        Poi(name="我的家", address="深圳市南山区", location="113.93,22.57", distance_m=1000),
    ],
    "科技园": [
        Poi(name="深圳科技园", address="深圳市南山区科技园", location="113.95,22.55", distance_m=3000),
        Poi(name="科技园地铁站", address="深圳市南山区科技园地铁站", location="113.95,22.54", distance_m=3100),
    ],
}


class MockPoiService(PoiSearchService):
    """Mock POI 搜索服务。"""

    def __init__(self):
        pass  # 不调用父类__init__

    def query_poi_list(self, destination: str, *, city: str | None = None) -> list[Poi]:
        return list(MOCK_POIS.get(destination, []))


# ── 非导航意图处理（模拟主助手）───────────────────────────────

def mock_non_nav_handler(text: str) -> str:
    """模拟主语音助手处理非导航请求。"""
    if "闹钟" in text:
        return "【主助手】你明天有3个闹钟：7:00（起床）、8:30（出门）、9:00（晨会）"
    if "天气" in text:
        return "【主助手】深圳今天多云转晴，26-32℃，东南风3级，空气质量优"
    if "笑话" in text or "讲个" in text:
        return "【主助手】程序员最讨厌的数字是什么？是1024，因为它总让人想起加班。"
    if "音乐" in text or "歌" in text:
        return "【主助手】好的，为你播放周杰伦的《晴天》"
    return f"【主助手】已为你处理：{text}"


# ── 场景演示脚本 ──────────────────────────────────────────────

SCENARIOS = {
    1: {
        "name": "场景1：无目的地反问",
        "steps": ["开始导航", "大新", "第一个"],
        "desc": "用户说'开始导航'（没提供目的地）→ 反问'请问要去哪里？' → 用户说'大新' → 搜索POI → 选择第一个 → 开始导航",
    },
    2: {
        "name": "场景2：直接导航（跳过POI选择）",
        "steps": ["导航到大新，直接导航，不要废话"],
        "desc": "用户说'导航到大新，直接导航，不要废话' → 跳过POI选择，直接开始第一个POI的导航",
    },
    3: {
        "name": "场景3：搜不到报错",
        "steps": ["导航到asdfghjklxyz"],
        "desc": "用户说'导航到xxx'（极端词）→ 正确应答'找不到xx，无法导航'，并收回控制权",
    },
    4: {
        "name": "场景4：列表后说'开始导航'（默认第一个）",
        "steps": ["导航到大新", "开始导航"],
        "desc": "出现POI列表后，用户说'开始导航'（没说第N个）→ 直接按照第一个地址开始导航",
    },
    5: {
        "name": "场景5：非导航意图拦截 + 主动召回 ⭐",
        "steps": ["导航到大新", "帮我看下我的闹钟", "导航到大新", "第一个"],
        "desc": "出现POI列表后，用户说'帮我看下我的闹钟'（非导航意图）→ 云侧前置判断层拦截，主助手处理闹钟 → 主动召回是否继续导航 → 用户继续 → 完成导航",
    },
}


# ── 输出格式化 ────────────────────────────────────────────────

def print_reply(reply, user_input: str):
    """格式化打印引擎回复。"""
    print(f"\n{'='*60}")
    print(f"👤 用户: {user_input}")
    print(f"{'─'*60}")
    print(f"🤖 回复: {reply.text}")
    print(f"{'─'*60}")
    print(f"   控制权: {reply.controller.value:12s} | 导航状态: {reply.nav_state.value}")
    if reply.nav_context.poi_list:
        print(f"   POI列表: {len(reply.nav_context.poi_list)} 个")
        for i, p in enumerate(reply.nav_context.poi_list[:3]):
            print(f"     {i+1}. {p.name}")
    if reply.nav_context.selected_poi:
        print(f"   已选POI: {reply.nav_context.selected_poi.name}")
    if reply.nav_context.is_in_navigation:
        print(f"   导航中: 是 (route_id={reply.nav_context.route_id})")
    if reply.handover_requested:
        print(f"   ⚠️  控制权交接: handover_requested=True (reason={reply.handover_reason})")
    if reply.should_recall:
        print(f"   🔔 主动召回: {reply.recall_text}")
    print(f"{'='*60}\n")


def print_status(engine: NavigationEngine):
    """打印当前引擎状态。"""
    print(f"\n📊 当前状态:")
    print(f"   控制权: {engine.controller.value}")
    print(f"   导航状态: {engine.nav_state.value}")
    print(f"   是否在导航中: {engine.is_in_navigation}")
    if engine.nav_context.destination:
        print(f"   目的地: {engine.nav_context.destination}")
    if engine.nav_context.poi_list:
        print(f"   POI列表: {len(engine.nav_context.poi_list)} 个")
    print()


def print_help():
    """打印帮助信息。"""
    print("""
📖 可用命令:
   直接输入用户指令（如"导航到大新"）
   status     - 查看当前引擎状态
   reset      - 重置引擎（新会话）
   scenario N - 自动演示场景N（1-5）
   scenarios  - 列出所有场景
   help       - 显示此帮助
   quit/exit  - 退出Demo

🎯 5个边界场景:
   场景1: 无目的地反问（"开始导航" → "请问要去哪里？"）
   场景2: 直接导航（"导航到大新，直接导航" → 跳过选择）
   场景3: 搜不到报错（"导航到xxx" → "找不到xx，无法导航"）
   场景4: 列表后说"开始导航"（默认第一个）
   场景5: 非导航意图拦截+主动召回 ⭐（"帮我看下闹钟" → 主助手处理 → 召回）
""")


# ── 主循环 ────────────────────────────────────────────────────

def run_demo(use_mock: bool = True, scenario: int | None = None):
    """运行交互式Demo。"""
    # 初始化引擎
    if use_mock:
        poi_service = MockPoiService()
        print("🔧 使用 Mock POI 数据（无需 API Key）")
    else:
        amap_key = os.getenv("AMAP_KEY", "")
        if not amap_key:
            print("❌ 未设置 AMAP_KEY 环境变量，自动切换到 Mock 模式")
            poi_service = MockPoiService()
        else:
            poi_service = PoiSearchService.from_key(amap_key)
            print(f"🔧 使用真实高德 API（Key: {amap_key[:8]}...）")

    nav_service = NavigationService()
    engine = NavigationEngine(
        poi_service,
        nav_service=nav_service,
        non_nav_handler=mock_non_nav_handler,
    )

    print("\n" + "="*60)
    print("🚗 雷鸟语音助手 × 高德导航接入 Demo")
    print("="*60)
    print_help()

    # 自动演示场景
    if scenario:
        if scenario not in SCENARIOS:
            print(f"❌ 无效场景编号: {scenario}（可选 1-5）")
            return
        s = SCENARIOS[scenario]
        print(f"\n🎬 自动演示: {s['name']}")
        print(f"📝 说明: {s['desc']}")
        input("\n按 Enter 开始演示...")
        for step in s["steps"]:
            reply = engine.handle(step)
            print_reply(reply, step)
        print("✅ 场景演示完成！")
        return

    # 交互循环
    while True:
        try:
            user_input = input("👤 请输入指令 (或 help): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 再见！")
            break

        if user_input.lower() == "help":
            print_help()
            continue

        if user_input.lower() == "status":
            print_status(engine)
            continue

        if user_input.lower() == "reset":
            engine.reset()
            print("🔄 引擎已重置\n")
            continue

        if user_input.lower() == "scenarios":
            print("\n🎯 可用场景:")
            for n, s in SCENARIOS.items():
                print(f"   场景{n}: {s['name']}")
            print()
            continue

        if user_input.lower().startswith("scenario "):
            try:
                n = int(user_input.split()[1])
                if n not in SCENARIOS:
                    print(f"❌ 无效场景编号: {n}（可选 1-5）")
                    continue
                s = SCENARIOS[n]
                print(f"\n🎬 演示: {s['name']}")
                print(f"📝 {s['desc']}\n")
                engine.reset()
                for step in s["steps"]:
                    reply = engine.handle(step)
                    print_reply(reply, step)
                print("✅ 场景演示完成！\n")
                continue
            except (ValueError, IndexError):
                print("❌ 用法: scenario N（N为1-5的数字）")
                continue

        # 正常处理用户输入
        try:
            reply = engine.handle(user_input)
            print_reply(reply, user_input)
        except Exception as e:
            print(f"❌ 处理出错: {e}\n")


# ── 入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导航对话引擎交互式 Demo")
    parser.add_argument("--mock", action="store_true", help="使用 Mock 数据（无需 API Key）")
    parser.add_argument("--real", action="store_true", help="使用真实高德 API（需 AMAP_KEY）")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4, 5], help="自动演示指定场景")
    args = parser.parse_args()

    use_mock = args.mock or not args.real
    run_demo(use_mock=use_mock, scenario=args.scenario)
