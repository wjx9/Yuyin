"""会话记忆 SessionHistory 单测：滑动窗口、落盘往返、损坏文件容错、纯内存模式。"""

from __future__ import annotations

import json

from routing.history import SessionHistory, Turn


def test_append_and_turns_order(tmp_path):
    h = SessionHistory(path=str(tmp_path / "h.json"))
    h.append("q1", "r1")
    h.append("q2", "r2")
    assert h.turns == [Turn("q1", "r1"), Turn("q2", "r2")]


def test_sliding_window_drops_oldest():
    h = SessionHistory(path=None, max_turns=3)
    for i in range(5):
        h.append(f"q{i}", f"r{i}")
    assert [t.query for t in h.turns] == ["q2", "q3", "q4"]


def test_save_load_roundtrip(tmp_path):
    path = str(tmp_path / "h.json")
    h1 = SessionHistory(path=path)
    h1.append("你好", "在的")
    h1.save()

    h2 = SessionHistory(path=path)
    h2.load()
    assert h2.turns == [Turn("你好", "在的")]


def test_load_missing_file_is_empty(tmp_path):
    h = SessionHistory(path=str(tmp_path / "nope.json"))
    h.load()
    assert h.turns == []


def test_load_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    h = SessionHistory(path=str(path))
    h.load()
    assert h.turns == []


def test_load_skips_malformed_items(tmp_path):
    path = tmp_path / "h.json"
    path.write_text(
        json.dumps([{"query": "ok", "response": "ok"}, {"query": 1}, "garbage"]),
        encoding="utf-8",
    )
    h = SessionHistory(path=str(path))
    h.load()
    assert h.turns == [Turn("ok", "ok")]


def test_memory_only_mode_does_not_write(tmp_path):
    path = tmp_path / "h.json"
    h = SessionHistory(path=None)
    h.append("q", "r")
    h.save()
    assert not path.exists()


def test_clear_removes_file(tmp_path):
    path = tmp_path / "h.json"
    h = SessionHistory(path=str(path))
    h.append("q", "r")
    h.save()
    assert path.exists()
    h.clear()
    assert not path.exists()
    assert h.turns == []


def test_long_response_truncated():
    h = SessionHistory(path=None)
    h.append("q", "x" * 5000)
    stored = h.turns[0].response
    assert len(stored) < 5000
    assert stored.endswith("（已截断）")
