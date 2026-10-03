from __future__ import annotations

from types import SimpleNamespace

from GameSentenceMiner.util import reading_sessions as rs
from GameSentenceMiner.util.database.session_review_tables import ReadingSessionsTable


def _line(i: int, ts: float, text: str = "文", game_id: str = "g1", game_name: str = "Game"):
    return SimpleNamespace(id=f"l{i}", timestamp=ts, line_text=text, game_id=game_id, game_name=game_name)


def test_split_into_sessions_by_gap():
    lines = [_line(0, 0), _line(1, 100), _line(2, 2000), _line(3, 2100), _line(4, 2200)]
    sessions = rs.split_into_sessions(lines, gap_seconds=1800)
    assert [(s.start_ts, s.end_ts, s.line_count) for s in sessions] == [(0, 100, 2), (2000, 2200, 3)]
    assert sessions[0].key == "g1:0" and sessions[0].source == rs.SESSION_SOURCE_AUTO
    assert sessions[1].char_count == 3 and sessions[1].line_ids == ["l2", "l3", "l4"]


def test_split_handles_unsorted_input_and_empty():
    assert rs.split_into_sessions([], 1800) == []
    sessions = rs.split_into_sessions([_line(1, 50), _line(0, 10)], 1800)
    assert sessions[0].line_ids == ["l0", "l1"]


def test_game_key_falls_back_to_game_name_for_rows_without_id():
    s = rs.split_into_sessions([_line(0, 0, game_id="", game_name="Manga Vol 1")], 1800)[0]
    assert s.game_key == "Manga Vol 1" and s.key == "Manga Vol 1:0"


def test_manual_session_overrides_gap_rule():
    # A manual session spanning a long pause stays one session; the rest splits by gap.
    lines = [_line(0, 0), _line(1, 5000), _line(2, 20000), _line(3, 20010)]
    manual = [ReadingSessionsTable(id=7, game_key="g1", start_ts=0, end_ts=6000, status="closed")]
    sessions = rs.apply_manual_sessions(lines, manual, gap_seconds=1800)
    assert [(s.source, s.line_count, s.manual_id) for s in sessions] == [("manual", 2, 7), ("auto", 2, None)]


def test_open_manual_session_extends_to_now():
    lines = [_line(0, 0), _line(1, 10**6)]
    manual = [ReadingSessionsTable(id=1, game_key="g1", start_ts=0, end_ts=None, status="open")]
    sessions = rs.apply_manual_sessions(lines, manual, gap_seconds=1800)
    assert len(sessions) == 1 and sessions[0].source == "manual" and sessions[0].line_count == 2


def test_duration_and_dict_shape():
    s = rs.split_into_sessions([_line(0, 10), _line(1, 70)], 1800)[0]
    d = s.to_dict()
    assert d["duration_seconds"] == 60 and "line_ids" not in d
    assert "line_ids" in s.to_dict(include_line_ids=True)
