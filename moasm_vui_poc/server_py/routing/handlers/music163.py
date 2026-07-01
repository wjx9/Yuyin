"""网易云音乐 Handler：点歌(搜+播) 与 播放控制(暂停/切歌/音量)。

为什么拆两个意图？
    "点歌"(我想听 X) 与 "控制"(暂停/下一首/大点声) 的触发语与参数形态完全不同，
    交给 Gemini 分类器直接在二者间选，比塞进一个 handler 再二次判断更稳——
    契合本项目"一能力一 Handler、新增能力零改分类器"的设计。两者共享同一 MusicService。

step 1 仅纯 PC：在线播放靠服务端本机的 ncm-cli + mpv，且需先在该机
`ncm-cli login` 扫码登录。未登录/失败时给可执行的提示，不抛栈。
"""

from __future__ import annotations

import re

from music163.errors import Music163Error
from music163.service import MusicService

from ..handler import Handler, RouteContext, RouteResult

# 去掉"我想听/放一首/来点/播放…的歌/音乐"等包裹词，抠出歌名/歌手关键词。
_PLAY_STRIP = re.compile(
    r"(我?想?要?听|放一?首|来一?首|来点儿?|播放|点歌|帮我?放|听首)|"
    r"的?(歌曲?|音乐|歌儿?)$"
)


def _play_keyword(query: str) -> str:
    kw = _PLAY_STRIP.sub("", query).strip(" 　，。,.!！?？、的")
    return kw or query


class MusicPlayHandler(Handler):
    intent = "music_play"
    description = (
        "点歌/听歌：搜索并播放一首具体的歌或某歌手的歌，"
        "如'我想听方大同的歌'、'放一首晴天'、'来点周杰伦'、'播放七里香'。"
        "仅用于'要听某首歌/某歌手'；暂停/切歌/调音量等控制类不走这里"
    )

    def __init__(self, service: MusicService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        if not self._service.is_logged_in():
            return RouteResult(
                text="网易云音乐还没登录。请在服务端那台电脑上执行 `ncm-cli login` 扫码登录后再点歌。",
                intent=self.intent,
            )
        keyword = _play_keyword(query)
        try:
            song = self._service.play_first(keyword, user_input=query)
        except Music163Error as e:
            return RouteResult(text=f"点歌失败：{e}", intent=self.intent)
        # data 用可序列化 dict（含 orpheus 深链）：CS 模式下回传客户端，供端侧拉起网易云 app（step 3.1）
        return RouteResult(text=f"正在播放：{song.label()}", data=song.to_client_dict(), intent=self.intent)


# 控制意图：关键词 → service 方法名（无参动作）
_ACTIONS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"暂停|停一下|别放了|先停"), "pause", "已暂停"),
    (re.compile(r"继续|接着放|恢复"), "resume", "已继续播放"),
    (re.compile(r"停止|关掉|关闭音乐|别听了|不听了"), "stop", "已停止播放"),
    (re.compile(r"下一[首个曲]|下首|换一?首|切歌"), "next", "已切到下一首"),
    (re.compile(r"上一[首个曲]|上首"), "prev", "已切到上一首"),
]
_VOLUME_HINT = re.compile(r"音量|声音|大声|小声|大点|小点|静音|外放")


class MusicControlHandler(Handler):
    intent = "music_control"
    # PC-only：暂停/切歌/音量都是对**服务端本机 mpv** 的控制。移动端是"点歌→深链拉起网易云 app、
    # 在手机上自己放"，服务端 mpv 根本不是它的播放目标，控制指令打过去只会停到 PC 上那路声音、
    # 手机 app 纹丝不动。故对 mobile 隐藏（能力清单 + 路由都不暴露），只在 chat_app / client_py（PC）可用。
    pc_only = True
    description = (
        "音乐播放控制：暂停/继续/停止/上一首/下一首/调音量，"
        "如'暂停'、'继续播放'、'下一首'、'声音大一点'、'音量调到50'、'静音'。"
        "仅控制正在播放的音乐，不用于点新歌"
    )

    def __init__(self, service: MusicService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        try:
            return self._dispatch(query)
        except Music163Error as e:
            return RouteResult(text=f"操作失败：{e}", intent=self.intent)

    def _dispatch(self, query: str) -> RouteResult:
        for pattern, method, ok_text in _ACTIONS:
            if pattern.search(query):
                getattr(self._service, method)()
                return RouteResult(text=ok_text, intent=self.intent)
        if _VOLUME_HINT.search(query):
            level = _target_volume(query)
            self._service.set_volume(level)
            return RouteResult(text=f"音量已调到 {level}", intent=self.intent)
        return RouteResult(
            text="没听懂要怎么控制播放（可以说：暂停 / 继续 / 下一首 / 声音大一点 / 音量调到50）。",
            intent=self.intent,
        )


def _target_volume(query: str) -> int:
    """从控制语里估个目标音量(0-100)：显式数字优先，否则按 静音/大/小 给档位。"""
    m = re.search(r"(\d{1,3})", query)
    if m:
        return max(0, min(100, int(m.group(1))))
    if re.search(r"静音|没声|别出声", query):
        return 0
    if re.search(r"大", query):
        return 80
    if re.search(r"小", query):
        return 30
    return 50
