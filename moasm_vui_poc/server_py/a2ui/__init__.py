"""A2UI 呈现层：把技能的文本/结构化结果转成 A2UI v0.9 消息，供富 UI 端渲染卡片。

分层定位：
    这是**服务端的呈现层**，位于 ChatService（server 包）之下、routing 之外——
    handler/routing 只产出语义结果（text/data/intent），"长什么样"由本包决定。
    新增一种卡片 = 在 cards.py 注册一个 builder，routing/providers 零改动。

协议：
    A2UI（Agent-to-UI）v0.9，与 Flutter 端 genui 库（package:genui 0.9.x）对齐。
    每轮返回一组消息：createSurface + updateComponents；根组件 id 必须是 "root"
    且为 Card 类型（穿戴设备约定：卡片式、单绿显示，样式由客户端主题决定，
    本层只产语义组件，不带任何颜色/样式信息）。
"""

from .cards import build_a2ui

__all__ = ["build_a2ui"]
