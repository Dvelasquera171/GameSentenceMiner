"""Tables for reading sessions and AI comprehension reviews.

A *reading session* is a contiguous stretch of lines from one game. Most sessions
are derived on demand from ``game_lines`` timestamps (see
``util/reading_sessions.py``); this module only persists the ones the user marks
explicitly, plus the AI review artifacts and quiz attempts.
"""

from __future__ import annotations

import time
from typing import List, Optional

from GameSentenceMiner.util.database.db import SQLiteDBTable

SESSION_SOURCE_MANUAL = "manual"
SESSION_STATUS_OPEN = "open"
SESSION_STATUS_CLOSED = "closed"

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_RUNNING = "running"
REVIEW_STATUS_DONE = "done"
REVIEW_STATUS_FAILED = "failed"


class ReadingSessionsTable(SQLiteDBTable):
    """User-marked sessions (Start/End buttons). Auto sessions are never stored here."""

    _table = "reading_sessions"
    _fields = ["game_key", "game_name", "start_ts", "end_ts", "source", "status", "created_at"]
    _types = [int, str, str, float, float, str, str, float]
    _pk = "id"
    _auto_increment = True

    def __init__(
        self,
        id: Optional[int] = None,
        game_key: Optional[str] = None,
        game_name: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        source: str = SESSION_SOURCE_MANUAL,
        status: str = SESSION_STATUS_OPEN,
        created_at: Optional[float] = None,
    ):
        self.id = id
        self.game_key = game_key or ""
        self.game_name = game_name or ""
        self.start_ts = float(start_ts) if start_ts is not None else time.time()
        self.end_ts = float(end_ts) if end_ts is not None else None
        self.source = source
        self.status = status
        self.created_at = created_at if created_at is not None else time.time()

    @classmethod
    def get_open(cls, game_key: Optional[str] = None) -> List["ReadingSessionsTable"]:
        if game_key:
            rows = cls._db.fetchall(
                f"SELECT * FROM {cls._table} WHERE status=? AND game_key=? ORDER BY start_ts DESC",
                (SESSION_STATUS_OPEN, game_key),
            )
        else:
            rows = cls._db.fetchall(
                f"SELECT * FROM {cls._table} WHERE status=? ORDER BY start_ts DESC", (SESSION_STATUS_OPEN,)
            )
        return [cls.from_row(r) for r in rows]

    @classmethod
    def get_for_game(cls, game_key: str, limit: int = 100) -> List["ReadingSessionsTable"]:
        rows = cls._db.fetchall(
            f"SELECT * FROM {cls._table} WHERE game_key=? ORDER BY start_ts DESC LIMIT ?", (game_key, limit)
        )
        return [cls.from_row(r) for r in rows]

    def close(self, end_ts: Optional[float] = None) -> None:
        self.end_ts = float(end_ts) if end_ts is not None else time.time()
        self.status = SESSION_STATUS_CLOSED
        self.save()


class SessionReviewsTable(SQLiteDBTable):
    """One AI review for a line range of one game.

    ``highlights`` is a dict: {"items": [Highlight...], "characters": [...],
    "may_have_missed_ja": [...], "may_have_missed_en": [...]}. ``quiz`` is a list of QuizQuestion dicts.
    """

    _table = "session_reviews"
    _fields = [
        "game_key",
        "game_name",
        "start_ts",
        "end_ts",
        "line_count",
        "char_count",
        "status",
        "stage",
        "progress",
        "error",
        "summary_ja",
        "summary_en",
        "highlights",
        "quiz",
        "provider",
        "model",
        "created_at",
        "updated_at",
    ]
    _types = [int, str, str, float, float, int, int, str, str, str, str, str, str, dict, list, str, str, float, float]
    _pk = "id"
    _auto_increment = True

    def __init__(
        self,
        id: Optional[int] = None,
        game_key: Optional[str] = None,
        game_name: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        line_count: int = 0,
        char_count: int = 0,
        status: str = REVIEW_STATUS_PENDING,
        stage: str = "",
        progress: str = "",
        error: str = "",
        summary_ja: str = "",
        summary_en: str = "",
        highlights: Optional[dict] = None,
        quiz: Optional[list] = None,
        provider: str = "",
        model: str = "",
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
    ):
        self.id = id
        self.game_key = game_key or ""
        self.game_name = game_name or ""
        self.start_ts = float(start_ts) if start_ts is not None else 0.0
        self.end_ts = float(end_ts) if end_ts is not None else 0.0
        self.line_count = int(line_count or 0)
        self.char_count = int(char_count or 0)
        self.status = status
        self.stage = stage
        self.progress = progress
        self.error = error
        self.summary_ja = summary_ja or ""
        self.summary_en = summary_en or ""
        self.highlights = highlights if highlights is not None else {}
        self.quiz = quiz if quiz is not None else []
        self.provider = provider or ""
        self.model = model or ""
        self.created_at = created_at if created_at is not None else time.time()
        self.updated_at = updated_at if updated_at is not None else time.time()

    @classmethod
    def list_recent(cls, game_key: Optional[str] = None, limit: int = 50) -> List["SessionReviewsTable"]:
        if game_key:
            rows = cls._db.fetchall(
                f"SELECT * FROM {cls._table} WHERE game_key=? ORDER BY created_at DESC LIMIT ?", (game_key, limit)
            )
        else:
            rows = cls._db.fetchall(f"SELECT * FROM {cls._table} ORDER BY created_at DESC LIMIT ?", (limit,))
        return [cls.from_row(r) for r in rows]

    def set_stage(self, stage: str, progress: str = "") -> None:
        self.stage = stage
        self.progress = progress
        self.status = REVIEW_STATUS_RUNNING
        self.updated_at = time.time()
        self.save()

    def mark_failed(self, error: str) -> None:
        self.status = REVIEW_STATUS_FAILED
        self.error = (error or "")[:2000]
        self.updated_at = time.time()
        self.save()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "game_key": self.game_key,
            "game_name": self.game_name,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "line_count": self.line_count,
            "char_count": self.char_count,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "error": self.error,
            "summary_ja": self.summary_ja,
            "summary_en": self.summary_en,
            "highlights": self.highlights,
            "quiz": self.quiz,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionQuizAttemptsTable(SQLiteDBTable):
    """Every graded answer, kept so the page can show history and future stats can use it."""

    _table = "session_quiz_attempts"
    _fields = ["review_id", "question_id", "answer", "grade", "created_at"]
    _types = [int, int, str, str, dict, float]
    _pk = "id"
    _auto_increment = True

    def __init__(
        self,
        id: Optional[int] = None,
        review_id: Optional[int] = None,
        question_id: Optional[str] = None,
        answer: str = "",
        grade: Optional[dict] = None,
        created_at: Optional[float] = None,
    ):
        self.id = id
        self.review_id = int(review_id) if review_id is not None else 0
        self.question_id = question_id or ""
        self.answer = answer or ""
        self.grade = grade if grade is not None else {}
        self.created_at = created_at if created_at is not None else time.time()

    @classmethod
    def for_review(cls, review_id: int) -> List["SessionQuizAttemptsTable"]:
        rows = cls._db.fetchall(
            f"SELECT * FROM {cls._table} WHERE review_id=? ORDER BY created_at ASC", (int(review_id),)
        )
        return [cls.from_row(r) for r in rows]


SESSION_REVIEW_TABLE_CLASSES = [ReadingSessionsTable, SessionReviewsTable, SessionQuizAttemptsTable]
