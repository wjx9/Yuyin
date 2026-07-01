"""网易云音乐 provider + 路由单测。

ncm-cli 不在 CI 环境，故用 fake subprocess.run 验证 argv 拼装/凭证注入/错误映射，
再用 FakeCli 验证 service 链路与两个 Handler。搜索结果的 JSON 形状按 ncm-cli 0.1.6
实测字段（encryptedId/originalId/name/artists/visible）构造。
"""

from __future__ import annotations

import subprocess

import pytest

from music163.client import NcmCli
from music163.errors import Music163Error
from music163.models import Song, parse_songs
from music163.service import MusicService

from routing.handler import RouteContext
from routing.handlers.music163 import (
    MusicControlHandler,
    MusicPlayHandler,
    _play_keyword,
    _target_volume,
)


class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRunner:
    def __init__(self, completed=None, raises=None):
        self._completed = completed or FakeCompleted(stdout='{"success": true}')
        self._raises = raises
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        if self._raises:
            raise self._raises
        return self._completed


# ---------- client ----------

def test_run_sets_credentials_then_subcommand(monkeypatch):
    runner = FakeRunner(FakeCompleted(stdout='{"success": true, "state": {}}'))
    monkeypatch.setattr(subprocess, "run", runner)

    cli = NcmCli("APP", "PK", command="ncm-cli")
    out = cli.run("state", raise_on_failure=False)

    assert out == {"success": True, "state": {}}
    # 首调先 config set 两条凭证，再跑真正子命令；全部带 --output json
    assert runner.calls[0]["argv"] == ["ncm-cli", "config", "set", "appId", "APP", "--output", "json"]
    assert runner.calls[1]["argv"] == ["ncm-cli", "config", "set", "privateKey", "PK", "--output", "json"]
    assert runner.calls[2]["argv"] == ["ncm-cli", "state", "--output", "json"]


def test_credentials_set_once_per_instance(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(subprocess, "run", runner)

    cli = NcmCli("APP", "PK")
    cli.run("pause")
    cli.run("resume")

    cfg = [c for c in runner.calls if c["argv"][1:3] == ["config", "set"]]
    assert len(cfg) == 2  # appId + privateKey，仅一轮


def test_node_launcher_command_is_split(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(subprocess, "run", runner)

    cli = NcmCli("A", "P", command="node C:/x/dist/index.js")
    cli.run("next")

    assert runner.calls[-1]["argv"] == ["node", "C:/x/dist/index.js", "next", "--output", "json"]


def test_success_false_raises_with_message(monkeypatch):
    runner = FakeRunner(FakeCompleted(stdout='{"success": false, "message": "未登录"}'))
    monkeypatch.setattr(subprocess, "run", runner)

    cli = NcmCli("A", "P")
    with pytest.raises(Music163Error) as ei:
        cli.run("search", ["all", "--keyword", "x"])
    assert "未登录" in str(ei.value)


def test_success_false_tolerated_when_not_raising(monkeypatch):
    runner = FakeRunner(FakeCompleted(stdout='{"success": false, "message": "未登录"}'))
    monkeypatch.setattr(subprocess, "run", runner)

    cli = NcmCli("A", "P")
    assert cli.run("login", ["--check"], raise_on_failure=False)["success"] is False


def test_missing_cli_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRunner(raises=FileNotFoundError()))
    with pytest.raises(Music163Error):
        NcmCli("A", "P").run("state")


def test_non_json_output_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRunner(FakeCompleted(stdout="not json")))
    with pytest.raises(Music163Error):
        NcmCli("A", "P").run("state")


def test_empty_stdout_rc0_is_success(monkeypatch):
    # play/pause 等动作类成功时无输出（rc=0）：返回 {}，不报错
    monkeypatch.setattr(subprocess, "run", FakeRunner(FakeCompleted(stdout="", returncode=0)))
    assert NcmCli("A", "P").run("play", ["--song"]) == {}


def test_code_200_envelope_ok(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRunner(FakeCompleted(stdout='{"code":200,"data":{}}')))
    assert NcmCli("A", "P").run("search", ["song"]) == {"code": 200, "data": {}}


def test_code_non200_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRunner(FakeCompleted(stdout='{"code":400,"message":"bad"}')))
    with pytest.raises(Music163Error) as ei:
        NcmCli("A", "P").run("search", ["song"])
    assert "bad" in str(ei.value)


# ---------- models ----------

# 形状对齐 ncm-cli 0.1.6 真实 `search song`：{code:200, data:{records:[...]}}，单曲带 duration。
_SEARCH_JSON = {
    "code": 200,
    "data": {
        "records": [
            {"name": "七里香", "id": "A" * 32, "originalId": "1", "duration": 240000,
             "visible": True, "artists": [{"name": "周杰伦"}]},
            {"name": "晴天", "id": "B" * 32, "originalId": "2", "duration": 270000,
             "visible": False, "artists": ["周杰伦"]},
        ]
    },
}


def test_parse_songs_extracts_fields_and_order():
    songs = parse_songs(_SEARCH_JSON)
    assert [s.name for s in songs] == ["七里香", "晴天"]
    assert songs[0].artists == ["周杰伦"]
    assert songs[0].encrypted_id == "A" * 32
    assert songs[0].original_id == "1"
    assert songs[1].visible is False


def test_parse_songs_empty_when_none():
    assert parse_songs({"success": True, "data": {}}) == []


# ---------- service / handlers ----------

class FakeCli:
    """记录 (subcommand, args, raise_on_failure)，按 subcommand 返回预设信封。"""

    def __init__(self, responses: dict | None = None):
        self._responses = responses or {}
        self.calls: list[tuple] = []

    def run(self, subcommand, args=None, *, raise_on_failure=True):
        self.calls.append((subcommand, args or [], raise_on_failure))
        resp = self._responses.get(subcommand, {"success": True})
        if raise_on_failure and isinstance(resp, dict) and resp.get("success") is False:
            raise Music163Error(str(resp.get("message")))
        return resp


def _ctx():
    return RouteContext(union_id=None, location=None)


def test_is_logged_in_reads_success():
    assert MusicService(FakeCli({"login": {"success": True}})).is_logged_in() is True
    assert MusicService(FakeCli({"login": {"success": False}})).is_logged_in() is False


def test_play_first_picks_first_visible_and_builds_play_argv():
    cli = FakeCli({"search": _SEARCH_JSON})
    song = MusicService(cli).play_first("周杰伦", user_input="放一首周杰伦")

    assert song.name == "七里香"  # 第一项即可播放(visible)
    search_call = next(c for c in cli.calls if c[0] == "search")
    assert search_call[1] == ["song", "--keyword", "周杰伦", "--userInput", "放一首周杰伦"]
    play_call = next(c for c in cli.calls if c[0] == "play")
    assert play_call[1] == ["--song", "--encrypted-id", "A" * 32, "--original-id", "1"]


def test_play_first_skips_invisible():
    only_invisible = {"code": 200, "data": {"records": [
        {"name": "x", "id": "C" * 32, "originalId": "3", "duration": 1000, "visible": False, "artists": []},
    ]}}
    with pytest.raises(Music163Error):
        MusicService(FakeCli({"search": only_invisible})).play_first("x")


def test_play_first_no_results_raises():
    with pytest.raises(Music163Error):
        MusicService(FakeCli({"search": {"code": 200, "data": {"records": []}}})).play_first("nope")


def test_control_methods_map_to_subcommands():
    cli = FakeCli()
    svc = MusicService(cli)
    svc.pause(); svc.next(); svc.set_volume(150)
    subs = [(c[0], c[1]) for c in cli.calls]
    assert ("pause", []) in subs
    assert ("next", []) in subs
    assert ("volume", ["100"]) in subs  # clamp 150 -> 100


# ---- play handler ----

def test_play_handler_prompts_when_not_logged_in():
    h = MusicPlayHandler(MusicService(FakeCli({"login": {"success": False}})))
    res = h.handle("我想听周杰伦的歌", _ctx())
    assert "登录" in res.text and res.intent == "music_play"


def test_play_handler_plays_when_logged_in():
    cli = FakeCli({"login": {"success": True}, "search": _SEARCH_JSON})
    res = MusicPlayHandler(MusicService(cli)).handle("放一首七里香", _ctx())
    assert res.text.startswith("正在播放：七里香")
    # data 是可序列化 dict（供 CS 回传客户端拉起 app），含 orpheus 深链
    assert res.data["kind"] == "music"
    assert res.data["name"] == "七里香"
    assert res.data["deeplink"] == "orpheus://song/1"  # _SEARCH_JSON 首歌 originalId=1


def test_song_deeplink_and_client_dict():
    s = Song(name="七里香", artists=["周杰伦"], encrypted_id="A" * 32, original_id="123")
    assert s.deeplink == "orpheus://song/123"
    assert s.web_url.endswith("id=123")
    d = s.to_client_dict()
    assert d["kind"] == "music" and d["originalId"] == "123" and d["deeplink"] == "orpheus://song/123"


def test_play_handler_maps_error_to_text():
    cli = FakeCli({"login": {"success": True}, "search": {"success": False, "message": "搜索挂了"}})
    res = MusicPlayHandler(MusicService(cli)).handle("放歌", _ctx())
    assert "点歌失败" in res.text and "搜索挂了" in res.text


@pytest.mark.parametrize("query,expected", [
    ("我想听方大同的歌", "方大同"),
    ("放一首晴天", "晴天"),
    ("来点周杰伦", "周杰伦"),
    ("播放七里香", "七里香"),
])
def test_play_keyword_strips_wrappers(query, expected):
    assert _play_keyword(query) == expected


# ---- control handler ----

@pytest.mark.parametrize("query,sub", [
    ("暂停一下", "pause"),
    ("继续播放", "resume"),
    ("下一首", "next"),
    ("上一首", "prev"),
    ("别听了", "stop"),
])
def test_control_handler_dispatches(query, sub):
    cli = FakeCli()
    res = MusicControlHandler(MusicService(cli)).handle(query, _ctx())
    assert cli.calls[-1][0] == sub
    assert res.intent == "music_control"


def test_control_handler_volume():
    cli = FakeCli()
    MusicControlHandler(MusicService(cli)).handle("音量调到 30", _ctx())
    assert cli.calls[-1] == ("volume", ["30"], True)


def test_control_handler_unknown():
    cli = FakeCli()
    res = MusicControlHandler(MusicService(cli)).handle("随便说点什么", _ctx())
    assert "没听懂" in res.text
    assert cli.calls == []  # 未触发任何 CLI


@pytest.mark.parametrize("query,vol", [
    ("音量调到50", 50), ("声音大一点", 80), ("小声点", 30), ("静音", 0), ("调下音量", 50),
])
def test_target_volume(query, vol):
    assert _target_volume(query) == vol
