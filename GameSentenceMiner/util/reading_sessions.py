"""Reading sessions: contiguous stretches of lines from one game.

Two sources, one shape:

* **auto** sessions are derived from ``game_lines`` timestamps with the stats
  ``session_gap_seconds`` rule (default 30 min). Nothing is stored.
* **manual** sessions come from the texthooker Start/End buttons and live in
  ``reading_sessions``. A manual session wins over the gap rule for its range.

Lines are grouped by ``game_key``: ``game_id`` when present, else ``game_name``
(old rows and non-game sources such as subtitles or manga OCR may lack an id).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Optional, Sequence

from GameSentenceMiner.util.config.configuration import get_stats_config, logger
from GameSentenceMiner.util.database.db import GameLinesTable
from GameSentenceMiner.util.database.session_review_tables import ReadingSessionsTable

SESSION_SOURCE_AUTO = "auto"
SESSION_SOURCE_MANUAL = "manual"


def line_game_key(line) -> str:
    return str(getattr(line, "game_id", "") or getattr(line, "game_name", "") or "")


@dataclass
class ReadingSession:
    key: str  # f"{game_key}:{int(start_ts)}" — stable id for auto sessions
    game_key: str
    game_name: str
    start_ts: float
    end_ts: float
    line_count: int
    char_count: int
    source: str = SESSION_SOURCE_AUTO
    manual_id: Optional[int] = None
    line_ids: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_ts - self.start_ts)

    def to_dict(self, include_line_ids: bool = False) -> dict:
        data = asdict(self)
        data["duration_seconds"] = self.duration_seconds
        if not include_line_ids:
            data.pop("line_ids", None)
        return data


def _sorted(lines: Iterable) -> List:
    return sorted((ln for ln in lines if ln.timestamp is not None), key=lambda ln: float(ln.timestamp))


def _session_from_lines(lines: Sequence, source: str = SESSION_SOURCE_AUTO, manual_id: Optional[int] = None):
    first, last = lines[0], lines[-1]
    game_key = line_game_key(first)
    return ReadingSession(
        key=f"{game_key}:{int(float(first.timestamp))}",
        game_key=game_key,
        game_name=str(getattr(first, "game_name", "") or ""),
        start_ts=float(first.timestamp),
        end_ts=float(last.timestamp),
        line_count=len(lines),
        char_count=sum(len(ln.line_text or "") for ln in lines),
        source=source,
        manual_id=manual_id,
        line_ids=[ln.id for ln in lines],
    )


def split_into_sessions(lines: Iterable, gap_seconds: float) -> List[ReadingSession]:
    """Pure function: group lines of ONE game into sessions by timestamp gap."""
    ordered = _sorted(lines)
    sessions: List[ReadingSession] = []
    bucket: List = []
    for ln in ordered:
        if bucket and float(ln.timestamp) - float(bucket[-1].timestamp) > gap_seconds:
            sessions.append(_session_from_lines(bucket))
            bucket = []
        bucket.append(ln)
    if bucket:
        sessions.append(_session_from_lines(bucket))
    return sessions


def apply_manual_sessions(
    lines: Iterable, manual: Sequence[ReadingSessionsTable], gap_seconds: float
) -> List[ReadingSession]:
    """Manual ranges take their lines whole; the remainder is split by the gap rule."""
    ordered = _sorted(lines)
    now = time.time()
    claimed: set = set()
    sessions: List[ReadingSession] = []
    for ms in sorted(manual, key=lambda m: m.start_ts):
        end = ms.end_ts if ms.end_ts is not None else now
        inside = [ln for ln in ordered if ms.start_ts <= float(ln.timestamp) <= end and ln.id not in claimed]
        if not inside:
            continue
        claimed.update(ln.id for ln in inside)
        sessions.append(_session_from_lines(inside, source=SESSION_SOURCE_MANUAL, manual_id=ms.id))
    rest = [ln for ln in ordered if ln.id not in claimed]
    sessions.extend(split_into_sessions(rest, gap_seconds))
    sessions.sort(key=lambda s: s.start_ts)
    return sessions


def _fetch_lines_for_game(game_key: str) -> List:
    # game_key is a game_id for modern rows, a game_name for legacy/non-game sources.
    rows = GameLinesTable.get_all_by_game_id(game_key) if game_key else []
    if not rows:
        rows = GameLinesTable.get_all_lines_for_scene(game_key)
    return rows


def list_sessions(game_key: str, limit: int = 50) -> List[ReadingSession]:
    gap = float(get_stats_config().session_gap_seconds)
    lines = _fetch_lines_for_game(game_key)
    manual = ReadingSessionsTable.get_for_game(game_key, limit=500)
    sessions = apply_manual_sessions(lines, manual, gap)
    return list(reversed(sessions))[:limit]


def get_session_lines(game_key: str, start_ts: float, end_ts: float) -> List:
    """Lines of one game inside [start_ts, end_ts], oldest first. Source of truth for a review."""
    lines = _fetch_lines_for_game(game_key)
    return [ln for ln in _sorted(lines) if start_ts <= float(ln.timestamp) <= end_ts]


def start_manual_session(game_key: str, game_name: str = "") -> ReadingSessionsTable:
    """Start button. Closes any other open session for the same game first."""
    for open_session in ReadingSessionsTable.get_open(game_key):
        open_session.close()
    session = ReadingSessionsTable(game_key=game_key, game_name=game_name, start_ts=time.time())
    session.save()
    logger.info(f"Started manual reading session {session.id} for {game_name or game_key}")
    return session


def end_manual_session(session_id: Optional[int] = None, game_key: Optional[str] = None) -> List[ReadingSessionsTable]:
    """End button, or an automatic hook (game closed / OBS scene changed) calling with game_key."""
    if session_id is not None:
        row = ReadingSessionsTable.get(session_id)
        targets = [row] if row else []
    else:
        targets = ReadingSessionsTable.get_open(game_key)
    for row in targets:
        if row.status != "closed":
            row.close()
    return targets
