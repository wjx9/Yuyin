"""装配工厂：根据可用配置组装一个 Dispatcher。

设计原则：
    - 每个 provider 是否启用，取决于其配置是否就绪（env 缺失则跳过，不报错）。
    - chitchat 必启用并作为 default_intent（Gemini key 是分流层的硬依赖）。
    - extra_handlers 允许调用方再塞入任意自定义 Handler —— 这就是"灵活增加能力"
      的对外口子：实现一个 Handler 传进来即可，分类器/分发器零改动。

注意分层：本工厂位于顶层编排层，可以 import 各 provider 的 config/build；
而各 provider 包之间彼此不感知。
"""

from __future__ import annotations

import os

from .classifier import GeminiClassifier, IntentClassifier, KeywordClassifier
from .dispatcher import Dispatcher
from .gemini import GeminiClient
from .handler import Handler
from .handlers import (
    AmapHandler,
    ChitchatHandler,
    ExpressTrackingHandler,
    MusicControlHandler,
    MusicPlayHandler,
    TencentHotNewsHandler,
    TencentNewsSearchHandler,
    TencentWeatherHandler,
    TripNowPersonalHandler,
    TripNowPublicHandler,
)


def build_dispatcher(
    *,
    classifier: IntentClassifier | None = None,
    extra_handlers: list[Handler] | None = None,
) -> Dispatcher:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        raise RuntimeError("缺少 GEMINI_API_KEY：分流层需要它做意图分类与闲聊兜底")
    gemini = GeminiClient(gemini_key)

    chitchat = ChitchatHandler(gemini)  # 兜底，必有
    handlers: list[Handler] = [chitchat]

    _try_add_tripnow(handlers)
    _try_add_kuaidi100(handlers)
    _try_add_amap(handlers, gemini)
    _try_add_tencent_news(handlers)
    _try_add_music163(handlers)

    if extra_handlers:
        handlers.extend(extra_handlers)

    # 回填全系统能力清单，让 chitchat 能如实回答"你能做什么"
    chitchat.set_capabilities([h.spec() for h in handlers])

    classifier = classifier or GeminiClassifier(gemini, fallback=KeywordClassifier())
    return Dispatcher(handlers, classifier, default_intent="chitchat")


def _try_add_tripnow(handlers: list[Handler]) -> None:
    if not os.getenv("TRIPNOW_API_KEY", "").strip():
        return
    from tripnow_client.config import Settings, build_transport

    settings = Settings.from_env()
    transport = build_transport(settings)
    handlers.append(TripNowPublicHandler(transport, model=settings.model))
    # mock_union_id：未真正接 OAuth 时，用配置里的测试账号(TRIPNOW_UNION_ID)冒充已登录身份
    handlers.append(
        TripNowPersonalHandler(transport, model=settings.model, mock_union_id=settings.union_id)
    )


def _try_add_kuaidi100(handlers: list[Handler]) -> None:
    if not (os.getenv("KUAIDI100_KEY", "").strip() and os.getenv("KUAIDI100_CUSTOMER", "").strip()):
        return
    from kuaidi100_client.config import Kuaidi100Settings, build_service

    handlers.append(ExpressTrackingHandler(build_service(Kuaidi100Settings.from_env())))


def _try_add_amap(handlers: list[Handler], gemini: GeminiClient) -> None:
    if not os.getenv("AMAP_KEY", "").strip():
        return
    from amap_client.config import AmapSettings, build_service

    from .handlers.amap import GeminiMapQueryParser

    # REST 后端的降级解析器：正常路径槽位随分类一次抽出（AmapHandler.slots），
    # 只有槽位为空时才会走到它（a2a 后端会忽略它）。
    service = build_service(AmapSettings.from_env(), parser=GeminiMapQueryParser(gemini))
    handlers.append(AmapHandler(service))


def _try_add_tencent_news(handlers: list[Handler]) -> None:
    if not os.getenv("TENCENT_NEWS_API_KEY", "").strip():
        return
    from tencent_news_client.config import TencentNewsSettings, build_service

    # 启用三个能力：全国热点榜 + 新闻搜索 + 多天天气预报。
    # search 承接地区新闻（"深圳的新闻"、"美国新闻"）与分类新闻（"科技新闻"）——
    # 这是 VUI 的高频场景，走 chitchat 联网检索既慢又不出自腾讯新闻，故回归 search；
    # 检索词/条数由各 handler 声明的 slots 在意图分类时一次抽出（整句话术喂
    # 全文检索会命中大量噪声），槽位为空时 handler 内部正则清洗兜底。
    # 流言核查(jiaozhen)本身较弱，仍由 chitchat 联网检索覆盖，不注册。
    service = build_service(TencentNewsSettings.from_env())
    handlers.append(TencentHotNewsHandler(service))
    handlers.append(TencentNewsSearchHandler(service))
    handlers.append(TencentWeatherHandler(service))


def _try_add_music163(handlers: list[Handler]) -> None:
    # 需 appId + privateKey；缺其一则不启用。OAuth 登录(扫码)与 mpv 安装是运行期前提，
    # 由 handler 在未登录时给提示，不在此阻塞装配。
    if not (os.getenv("MUSIC163_APPID", "").strip() and os.getenv("MUSIC163_PRIVATE_KEY", "").strip()):
        return
    from music163.config import Music163Settings, build_service

    service = build_service(Music163Settings.from_env())
    handlers.append(MusicPlayHandler(service))
    handlers.append(MusicControlHandler(service))
