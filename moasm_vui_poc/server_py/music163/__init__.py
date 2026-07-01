"""网易云音乐能力（独立 provider）：搜歌 / 点歌 / 播放控制。

官方执行面是本地 CLI（@music163/ncm-cli，在线播放依赖本机 mpv，仅 mac/win），
本包把它薄封装成与其他 provider 一致的 service 形态供分流层调用。
背景与分阶段计划见 docs/introduce.md。
"""

from .client import NcmCli
from .config import Music163Settings, build_service
from .errors import Music163Error
from .models import Song, parse_songs
from .service import MusicService

__all__ = [
    "NcmCli",
    "Music163Settings",
    "build_service",
    "Music163Error",
    "Song",
    "parse_songs",
    "MusicService",
]
