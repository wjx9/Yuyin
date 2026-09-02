"""导航对话引擎测试用例。

覆盖：
- 正常流程（4步导航）
- 场景1：无目的地反问
- 场景2：直接导航（跳过POI选择）
- 场景3：搜不到报错
- 场景4：列表后说"开始导航"默认第一个
- 场景5：非导航意图拦截 + 主动召回
- 结束导航 / 重新导航
- 取消

使用 MockPoiService 避免依赖真实高德API。
运行：python -m pytest server_py/navigation/test_navigation.py -v
"""

from __future__ import annotations

import os
import sys
import pytest

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


# ── Mock POI 服务 ────────────────────────────────────────────

class MockPoiService(PoiSearchService):
    """模拟POI搜索服务，不依赖真实API。"""

    def __init__(self, results: dict[str, list[Poi]] | None = None):
        # 不调用父类__init__（避免创建AmapRestClient）
        self._results = results or {}
        self._default_city = "深圳"
        self._default_location = "114.0579,22.5431"
        self._max_pois = 10

    def query_poi_list(self, destination: str, *, city: str | None = None) -> list[Poi]:
        return list(self._results.get(destination, []))


def _make_pois(names: list[str]) -> list[Poi]:
    """快速构造POI列表。"""
    return [
        Poi(name=name, address=f"{name}地址", location=f"114.0,22.5", distance_m=1000 + i * 500)
        for i, name in enumerate(names)
    ]


# ── Fixture ──────────────────────────────────────────────────

@pytest.fixture
def engine():
    """创建带mock数据的导航引擎。"""
    mock_data = {
        "大新": _make_pois(["大新地铁站", "大新公园", "大新地铁站B口"]),
        "深圳湾公园": _make_pois(["深圳湾公园"]),  # 唯一POI
        "公司": _make_pois(["雷鸟创新科技有限公司"]),
        "家": _make_pois(["我的家"]),
        # 极端词：空结果
    }
    poi_service = MockPoiService(mock_data)
    nav_service = NavigationService()
    eng = NavigationEngine(poi_service, nav_service=nav_service)
    yield eng
    eng.reset()


# ── 正常流程：4步导航 ────────────────────────────────────────

class TestNormalFlow:
    """正常导航流程：导航到大新 → 选择第一个 → 开始导航。"""

    def test_step1_nav_with_destination(self, engine):
        """步骤1：用户说"导航到大新"，返回POI列表并询问选择。"""
        reply = engine.handle("导航到大新")
        assert "大新" in reply.text
        assert "第几个" in reply.text or "选择" in reply.text
        assert reply.controller == Controller.AMAP_AGENT
        assert reply.nav_state == NavState.WAITING_POI_SELECTION
        assert len(reply.nav_context.poi_list) == 3

    def test_step2_select_first(self, engine):
        """步骤2：用户说"第一个"，启动导航。"""
        engine.handle("导航到大新")  # 先进入POI选择状态
        reply = engine.handle("第一个")
        assert "导航" in reply.text
        assert "大新地铁站" in reply.text
        assert reply.nav_state == NavState.NAVIGATING
        assert reply.nav_context.is_in_navigation is True
        assert engine.is_in_navigation is True

    def test_full_flow(self, engine):
        """完整4步流程验证。"""
        # 步骤1
        r1 = engine.handle("导航到大新")
        assert r1.nav_state == NavState.WAITING_POI_SELECTION

        # 步骤2
        r2 = engine.handle("第一个")
        assert r2.nav_state == NavState.NAVIGATING
        assert r2.nav_context.selected_poi.name == "大新地铁站"

        # 导航中
        assert engine.is_in_navigation is True
        assert engine.controller == Controller.AMAP_AGENT


# ── 场景1：无目的地反问 ──────────────────────────────────────

class TestScenario1NoDestination:
    """场景1：用户说"开始导航"，没提供目的地。"""

    def test_ask_for_destination(self, engine):
        """期望：识别到导航意图但缺少参数，反问"请问要去哪里？"。"""
        reply = engine.handle("开始导航")
        assert "去哪里" in reply.text or "哪" in reply.text
        assert reply.controller == Controller.AMAP_AGENT
        assert reply.nav_state == NavState.WAITING_DESTINATION

    def test_then_provide_destination(self, engine):
        """用户补充目的地后，开始POI搜索。"""
        engine.handle("开始导航")  # 反问
        reply = engine.handle("大新")
        assert "大新" in reply.text
        assert reply.nav_state == NavState.WAITING_POI_SELECTION
        assert len(reply.nav_context.poi_list) == 3

    def test_navigate_bar(self, engine):
        """"导航吧"也应识别为无目的地导航意图。"""
        reply = engine.handle("导航吧")
        assert "去哪里" in reply.text or "哪" in reply.text
        assert reply.nav_state == NavState.WAITING_DESTINATION


# ── 场景2：直接导航（跳过POI选择）────────────────────────────

class TestScenario2DirectNavigation:
    """场景2：用户说"导航到大新，直接导航，不要废话"。"""

    def test_direct_navigation(self, engine):
        """期望：跳过POI选择，直接开始第一个POI的导航。"""
        reply = engine.handle("导航到大新，直接导航，不要废话")
        assert "导航" in reply.text
        assert "大新地铁站" in reply.text  # 第一个POI
        assert reply.nav_state == NavState.NAVIGATING
        assert reply.nav_context.is_in_navigation is True
        # 没有经过WAITING_POI_SELECTION状态
        assert engine.is_in_navigation is True

    def test_direct_navigation_variants(self, engine):
        """多种直接导航表达方式。"""
        for text in ["导航到大新直接走", "带我去大新别问", "去大新直接出发"]:
            engine.reset()
            reply = engine.handle(text)
            assert reply.nav_state == NavState.NAVIGATING, f"{text} 应该直接导航"


# ── 场景3：搜不到报错 ────────────────────────────────────────

class TestScenario3PoiNotFound:
    """场景3：用户说"导航到xxx"（极端词，搜不到任何POI）。"""

    def test_poi_not_found(self, engine):
        """期望：正确应答"找不到xx，无法导航"，并收回控制权。"""
        reply = engine.handle("导航到asdfghjklxyz")
        assert "找不到" in reply.text or "无法" in reply.text
        assert "asdfghjklxyz" in reply.text
        assert reply.controller == Controller.PRIMARY  # 收回控制权
        assert reply.nav_state == NavState.IDLE
        assert engine.is_in_navigation is False

    def test_poi_not_found_empty_word(self, engine):
        """空结果的另一种表达。"""
        reply = engine.handle("导航到一个根本不存在的地方zzz")
        assert "找不到" in reply.text or "无法" in reply.text


# ── 场景4：列表后说"开始导航"默认第一个 ──────────────────────

class TestScenario4ConfirmAfterList:
    """场景4：出现POI列表后，用户说"开始导航"（没说第N个）。"""

    def test_confirm_after_list(self, engine):
        """期望：直接按照第一个地址开始导航。"""
        engine.handle("导航到大新")  # 进入POI选择
        reply = engine.handle("开始导航")
        assert "导航" in reply.text
        assert "大新地铁站" in reply.text  # 第一个POI
        assert reply.nav_state == NavState.NAVIGATING
        assert reply.nav_context.selected_poi.name == "大新地铁站"

    def test_confirm_variants(self, engine):
        """多种确认表达方式。"""
        for text in ["走吧", "出发", "就这个", "赶紧走"]:
            engine.reset()
            engine.handle("导航到大新")
            reply = engine.handle(text)
            assert reply.nav_state == NavState.NAVIGATING, f"{text} 应该确认导航"
            assert reply.nav_context.selected_poi.name == "大新地铁站"


# ── 场景5：非导航意图拦截 + 主动召回 ⭐核心场景 ─────────────

class TestScenario5NonNavigationIntercept:
    """场景5：出现POI列表后，用户说"帮我看下我的闹钟"（非导航意图）。

    核心验证：
    1. 云侧前置判断层拦截，不转发给Agent
    2. 由主助手处理非导航请求
    3. 保存导航上下文
    4. 主动召回用户是否继续导航
    """

    def test_intercept_during_poi_selection(self, engine):
        """POI选择阶段被非导航意图打断。"""
        engine.handle("导航到大新")  # 进入POI选择

        reply = engine.handle("帮我看下我的闹钟")

        # 主助手处理了闹钟请求
        assert "主助手" in reply.text or "闹钟" in reply.text
        # 主动召回
        assert reply.should_recall is True
        assert "继续导航" in reply.recall_text or "大新" in reply.recall_text
        # 控制权收回
        assert reply.controller == Controller.PRIMARY
        # 导航上下文保留
        assert len(reply.nav_context.poi_list) == 3
        assert reply.nav_context.destination == "大新"

    def test_intercept_handover_flag(self, engine):
        """验证handover_requested标志。"""
        engine.handle("导航到大新")
        reply = engine.handle("今天天气怎么样")
        assert reply.handover_requested is True
        assert reply.handover_reason == "non_navigation_intercept"

    def test_intercept_during_waiting_destination(self, engine):
        """等待目的地阶段被非导航意图打断。"""
        engine.handle("开始导航")  # 等待目的地
        reply = engine.handle("讲个笑话")
        assert reply.should_recall is True
        assert "去哪里" in reply.recall_text or "导航" in reply.recall_text

    def test_navigation_not_interrupted_during_navigating(self, engine):
        """导航中问非导航问题，导航继续进行（控制权保持在Agent）。"""
        engine.handle("导航到大新，直接导航")  # 直接进入导航
        assert engine.is_in_navigation is True

        reply = engine.handle("今天天气怎么样")
        # 导航仍在进行
        assert engine.is_in_navigation is True
        # 控制权保持在Agent（导航继续）
        assert reply.controller == Controller.AMAP_AGENT

    def test_multiple_non_navigation_requests(self, engine):
        """连续多个非导航请求。"""
        engine.handle("导航到大新")

        r1 = engine.handle("帮我看下闹钟")
        assert r1.should_recall is True

        # 用户继续问非导航问题
        r2 = engine.handle("今天天气怎么样")
        # 主助手处理
        assert "主助手" in r2.text or "天气" in r2.text

    def test_resume_after_intercept(self, engine):
        """被打断后用户说"继续"，恢复导航流程。"""
        engine.handle("导航到大新")
        engine.handle("帮我看下闹钟")  # 打断

        # 用户说继续（模拟：重新进入导航流程）
        # 注意：POC中"继续"需要重新发起导航，因为控制权已收回
        reply = engine.handle("导航到大新")
        assert reply.nav_state == NavState.WAITING_POI_SELECTION

        reply2 = engine.handle("第一个")
        assert reply2.nav_state == NavState.NAVIGATING


# ── 导航控制：结束 / 重新导航 / 取消 ─────────────────────────

class TestNavigationControl:
    """导航控制指令。"""

    def test_stop_navigation(self, engine):
        """结束导航。"""
        engine.handle("导航到大新，直接导航")
        assert engine.is_in_navigation is True

        reply = engine.handle("结束导航")
        assert "结束" in reply.text or "停止" in reply.text
        assert engine.is_in_navigation is False
        assert reply.controller == Controller.PRIMARY

    def test_reroute(self, engine):
        """重新导航到新目的地。"""
        engine.handle("导航到大新，直接导航")
        assert engine.is_in_navigation is True

        reply = engine.handle("重新导航到公司")
        assert "公司" in reply.text or "雷鸟" in reply.text
        assert engine.is_in_navigation is True
        assert reply.nav_context.selected_poi.name == "雷鸟创新科技有限公司"

    def test_cancel_during_selection(self, engine):
        """POI选择阶段取消。"""
        engine.handle("导航到大新")
        reply = engine.handle("取消")
        assert reply.controller == Controller.PRIMARY
        assert reply.nav_state == NavState.IDLE

    def test_cancel_during_navigation(self, engine):
        """导航中取消。"""
        engine.handle("导航到大新，直接导航")
        reply = engine.handle("取消")
        assert engine.is_in_navigation is False
        assert "取消" in reply.text


# ── 唯一POI直接导航 ──────────────────────────────────────────

class TestSinglePoi:
    """唯一POI时直接导航（不询问选择）。"""

    def test_single_poi_auto_navigate(self, engine):
        """只有一个POI时，直接启动导航。"""
        reply = engine.handle("导航到深圳湾公园")
        assert reply.nav_state == NavState.NAVIGATING
        assert "深圳湾公园" in reply.text
        # 没有经过询问选择
        assert engine.is_in_navigation is True


# ── 常用地址：家/公司 ────────────────────────────────────────

class TestCommonAddress:
    """常用地址导航。"""

    def test_navigate_home(self, engine):
        """导航到家。"""
        reply = engine.handle("导航到家")
        assert reply.nav_state == NavState.NAVIGATING
        assert "我的家" in reply.text

    def test_navigate_company(self, engine):
        """导航到公司。"""
        reply = engine.handle("去公司")
        assert reply.nav_state == NavState.NAVIGATING
        assert "雷鸟" in reply.text


# ── 状态机验证 ────────────────────────────────────────────────

class TestStateMachine:
    """状态机转移验证。"""

    def test_idle_to_waiting_dest(self, engine):
        assert engine.nav_state == NavState.IDLE
        engine.handle("开始导航")
        assert engine.nav_state == NavState.WAITING_DESTINATION

    def test_waiting_dest_to_poi_searching(self, engine):
        engine.handle("开始导航")
        engine.handle("大新")
        # 搜索后直接到WAITING_POI_SELECTION（因为有多个结果）
        assert engine.nav_state == NavState.WAITING_POI_SELECTION

    def test_poi_selection_to_navigating(self, engine):
        engine.handle("导航到大新")
        assert engine.nav_state == NavState.WAITING_POI_SELECTION
        engine.handle("第一个")
        assert engine.nav_state == NavState.NAVIGATING

    def test_navigating_to_idle_after_stop(self, engine):
        engine.handle("导航到大新，直接导航")
        assert engine.nav_state == NavState.NAVIGATING
        engine.handle("结束导航")
        assert engine.nav_state == NavState.IDLE

    def test_controller_transitions(self, engine):
        """控制权转移验证。"""
        assert engine.controller == Controller.PRIMARY
        engine.handle("导航到大新，直接导航")  # 直接进入导航
        assert engine.controller == Controller.AMAP_AGENT
        engine.handle("结束导航")
        assert engine.controller == Controller.PRIMARY


# ── 运行入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
