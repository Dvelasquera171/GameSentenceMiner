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


import pytest  # noqa: E402

from GameSentenceMiner.util.database.db import SQLiteDB  # noqa: E402


@pytest.fixture
def session_db(tmp_path):
    db = SQLiteDB(str(tmp_path / "sessions.db"))
    original = ReadingSessionsTable._db
    ReadingSessionsTable.set_db(db)
    yield db
    ReadingSessionsTable._db = original
    db.close()


def _open(game_key, game_name):
    return rs.start_manual_session(game_key, game_name)


def test_scene_change_ends_sessions_of_other_games(session_db):
    keep = _open("g1", "Game One")
    other = _open("g2", "Game Two")
    closed = rs.end_sessions_on_game_change("Game One")
    assert [row.id for row in closed] == [other.id]
    assert ReadingSessionsTable.get(other.id).status == "closed"
    assert ReadingSessionsTable.get(keep.id).status == "open"
    # Repeating the event is harmless.
    assert rs.end_sessions_on_game_change("Game One") == []


def test_scene_change_to_empty_name_keeps_sessions(session_db):
    keep = _open("g1", "Game One")
    assert rs.end_sessions_on_game_change("") == []
    assert ReadingSessionsTable.get(keep.id).status == "open"


def test_game_closed_ends_only_that_games_sessions(session_db):
    gone = _open("g1", "Game One")
    keep = _open("Manga Vol 1", "Manga Vol 1")
    closed = rs.end_sessions_for_game("Game One")
    assert [row.id for row in closed] == [gone.id]
    assert ReadingSessionsTable.get(keep.id).status == "open"
    # Sessions keyed by name (no games-table id) match too.
    assert [row.id for row in rs.end_sessions_for_game("Manga Vol 1")] == [keep.id]
    assert rs.end_sessions_for_game("") == []


def test_window_monitor_ends_session_once_after_grace(monkeypatch):
    from GameSentenceMiner.util.platform import windows_window_monitor as wm

    calls = []
    monkeypatch.setattr(rs, "end_sessions_for_game", lambda name: calls.append(name) or [])
    monitor = object.__new__(wm.WindowsWindowStateMonitor)
    monitor._target_lost_since = None
    monitor._session_ended_for_lost_target = False
    monitor.last_scene_name = "Game One"
    monitor._end_reading_session_after_target_lost(1000.0)
    monitor._end_reading_session_after_target_lost(1000.0 + wm.TARGET_LOST_SESSION_END_SECONDS - 1)
    assert calls == []  # a restart or loading screen within the grace period keeps the session
    monitor._end_reading_session_after_target_lost(1000.0 + wm.TARGET_LOST_SESSION_END_SECONDS)
    monitor._end_reading_session_after_target_lost(1000.0 + 500)
    assert calls == ["Game One"]


def test_obs_scene_change_ends_other_games_sessions(monkeypatch):
    import threading

    from GameSentenceMiner.obs import service as obs_service

    calls = []
    monkeypatch.setattr(rs, "end_sessions_on_game_change", lambda name: calls.append(name) or [])
    monkeypatch.setattr(obs_service.gsm_state, "current_game", obs_service.gsm_state.current_game)
    svc = object.__new__(obs_service.OBSService)
    svc._state_lock = threading.Lock()
    svc.state = obs_service.OBSState()
    svc.check_output = False
    svc._refresh_scene_items = lambda name: None
    svc._schedule_fit_to_screen = lambda name, delay: None
    svc._handle_current_program_scene_changed(SimpleNamespace(scene_name="Game Two"))
    assert calls == ["Game Two"]
