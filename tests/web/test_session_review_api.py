from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from GameSentenceMiner.util.config.configuration import Ai, General
from GameSentenceMiner.util.database.db import SQLiteDB
from GameSentenceMiner.util.database.session_review_tables import (
    SESSION_REVIEW_TABLE_CLASSES,
    SessionQuizAttemptsTable,
    SessionReviewsTable,
)
from GameSentenceMiner.web import session_review_api, texthooking_page


@pytest.fixture
def temp_tables():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SQLiteDB(path)
    originals = {cls: cls._db for cls in SESSION_REVIEW_TABLE_CLASSES}
    for cls in SESSION_REVIEW_TABLE_CLASSES:
        cls.set_db(db)
    yield db
    for cls, original in originals.items():
        cls._db = original
    db.close() if hasattr(db, "close") else None
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def client(temp_tables):
    # Own app: the shared texthooker app refuses new routes once another test has used it.
    app = Flask(__name__, template_folder=str(Path(texthooking_page.__file__).parent / "templates"))
    session_review_api.register_session_review_routes(app)
    app.config["TESTING"] = True
    return app.test_client()


def _configured(monkeypatch):
    monkeypatch.setattr(
        session_review_api,
        "get_config",
        lambda: SimpleNamespace(
            ai=Ai(provider="OpenAI", open_ai_api_key="k", open_ai_model="m", open_ai_url="http://x"), general=General()
        ),
    )


def _line(i, ts, text="文"):
    return SimpleNamespace(id=f"l{i}", timestamp=ts, line_text=text, game_id="g1", game_name="Game")


def test_generate_requires_range(client):
    assert client.post("/api/review/generate", json={"game_key": "g1"}).status_code == 400


def test_generate_without_ai_opens_setup(client, monkeypatch):
    monkeypatch.setattr(session_review_api, "get_config", lambda: SimpleNamespace(ai=Ai(), general=General()))
    monkeypatch.setattr(session_review_api, "ai_setup_required", lambda automatic: {"code": "ai_setup_required"})
    res = client.post("/api/review/generate", json={"game_key": "g1", "start_ts": 0, "end_ts": 10})
    assert res.status_code == 400 and res.json["code"] == "ai_setup_required"


def test_generate_creates_row_and_starts_job(client, monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(session_review_api.reading_sessions, "get_session_lines", lambda *a: [_line(0, 1), _line(1, 2)])
    started = []
    monkeypatch.setattr(session_review_api, "start_review_job", lambda rid, qc=None: started.append((rid, qc)) or True)

    res = client.post("/api/review/generate", json={"game_key": "g1", "start_ts": 0, "end_ts": 10, "question_count": 3})
    assert res.status_code == 202
    review = SessionReviewsTable.get(res.json["review_id"])
    assert review.status == "running" and review.line_count == 2 and review.char_count == 2
    assert started == [(review.id, 3)]

    polled = client.get(f"/api/review/reviews/{review.id}").json
    assert polled["status"] == "running" and polled["stage"] == "queued"


def test_generate_with_no_lines_is_404(client, monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(session_review_api.reading_sessions, "get_session_lines", lambda *a: [])
    assert client.post("/api/review/generate", json={"game_key": "g1", "start_ts": 0, "end_ts": 10}).status_code == 404


def test_run_review_job_persists_result(monkeypatch):
    review = SessionReviewsTable(game_key="g1", game_name="Game", start_ts=0, end_ts=10, status="running")
    review.save()
    monkeypatch.setattr(session_review_api, "_review_lines", lambda r: [])

    class FakeGen:
        ai = SimpleNamespace(
            config_snapshot=SimpleNamespace(ai=SimpleNamespace(provider="OpenAI")),
            _get_model_for_provider=lambda cfg: "m",
        )

        def run(self, lines, title, progress=None, question_count=None):
            progress("digest", "1/1")
            return SimpleNamespace(
                to_dict=lambda: {
                    "summary_ja": "要約",
                    "summary_en": "Summary",
                    "highlights": [{"quote": "x"}],
                    "quiz": [{"id": "q1-1", "question_ja": "?"}],
                    "characters": [],
                    "may_have_missed_ja": ["a"],
                    "may_have_missed_en": ["b"],
                },
                line_count=1,
                char_count=5,
                quiz=[1],
            )

    monkeypatch.setattr(session_review_api, "build_generator", lambda logger: FakeGen())
    session_review_api.run_review_job(review.id, question_count=1)

    saved = SessionReviewsTable.get(review.id)
    assert saved.status == "done" and saved.summary_ja == "要約" and saved.model == "m"
    assert saved.highlights["items"] == [{"quote": "x"}] and saved.highlights["may_have_missed_ja"] == ["a"]
    assert saved.quiz[0]["id"] == "q1-1" and saved.char_count == 5


def test_run_review_job_records_failure(monkeypatch):
    review = SessionReviewsTable(game_key="g1", start_ts=0, end_ts=10, status="running")
    review.save()
    monkeypatch.setattr(session_review_api, "_review_lines", lambda r: [])

    class Boom:
        def run(self, *a, **k):
            raise session_review_api.SessionReviewError("no JSON")

        ai = SimpleNamespace(
            config_snapshot=SimpleNamespace(ai=SimpleNamespace(provider="p")), _get_model_for_provider=lambda c: "m"
        )

    monkeypatch.setattr(session_review_api, "build_generator", lambda logger: Boom())
    session_review_api.run_review_job(review.id)
    saved = SessionReviewsTable.get(review.id)
    assert saved.status == "failed" and "no JSON" in saved.error


def test_grade_stores_attempt(client, monkeypatch):
    _configured(monkeypatch)
    review = SessionReviewsTable(
        game_key="g1",
        game_name="Game",
        start_ts=0,
        end_ts=10,
        status="done",
        quiz=[{"id": "q1-1", "kind": "events", "question_ja": "?", "source_line_ids": ["missing"]}],
    )
    review.save()

    class FakeGen:
        def grade_answer(self, question, answer, source_lines, title):
            assert question.id == "q1-1" and answer == "答え" and source_lines == []
            return SimpleNamespace(
                verdict="correct", score=100, feedback_ja="", feedback_en="", japanese_fixes=[], model_answer_ja=""
            )

    monkeypatch.setattr(session_review_api, "build_generator", lambda logger: FakeGen())
    monkeypatch.setattr(session_review_api.GameLinesTable, "get", classmethod(lambda cls, lid: None))

    res = client.post(f"/api/review/reviews/{review.id}/grade", json={"question_id": "q1-1", "answer": "答え"})
    assert res.status_code == 200 and res.json["grade"]["verdict"] == "correct"
    attempts = SessionQuizAttemptsTable.for_review(review.id)
    assert len(attempts) == 1 and attempts[0].grade["score"] == 100
    assert client.get(f"/api/review/reviews/{review.id}/attempts").json["attempts"][0]["answer"] == "答え"


def test_grade_rejects_unknown_question_and_unready_review(client, monkeypatch):
    _configured(monkeypatch)
    review = SessionReviewsTable(game_key="g1", start_ts=0, end_ts=10, status="done", quiz=[{"id": "q1-1"}])
    review.save()
    assert (
        client.post(f"/api/review/reviews/{review.id}/grade", json={"question_id": "nope", "answer": "x"}).status_code
        == 404
    )
    running = SessionReviewsTable(game_key="g1", start_ts=0, end_ts=10, status="running")
    running.save()
    assert (
        client.post(f"/api/review/reviews/{running.id}/grade", json={"question_id": "q1-1", "answer": "x"}).status_code
        == 404
    )


def test_review_page_renders(client):
    res = client.get("/review")
    assert res.status_code == 200 and b"review.js" in res.data


def test_session_lines_route(client, monkeypatch):
    rows = [
        SimpleNamespace(id="l1", timestamp=5.0, line_text="一行"),
        SimpleNamespace(id="l2", timestamp=6.0, line_text="二"),
    ]
    seen = []
    monkeypatch.setattr(session_review_api.reading_sessions, "get_session_lines", lambda *a: seen.append(a) or rows)
    data = client.get("/api/review/session-lines?game_key=g1&start_ts=0&end_ts=10").json
    assert data == {
        "lines": [{"id": "l1", "timestamp": 5.0, "text": "一行"}, {"id": "l2", "timestamp": 6.0, "text": "二"}],
        "char_count": 3,
    }
    assert seen == [("g1", 0.0, 10.0)]
    assert client.get("/api/review/session-lines?game_key=g1&start_ts=10&end_ts=0").status_code == 400


def test_remove_manual_session_mark(client):
    from GameSentenceMiner.util.database.session_review_tables import ReadingSessionsTable

    row = ReadingSessionsTable(game_key="g1", game_name="Game", start_ts=1.0, end_ts=2.0, status="closed")
    row.save()
    assert client.post(f"/api/review/sessions/{row.id}/delete").status_code == 200
    assert ReadingSessionsTable.get(row.id) is None
    assert client.post(f"/api/review/sessions/{row.id}/delete").status_code == 404


def test_end_sessions_by_game_name(client):
    from GameSentenceMiner.util.database.session_review_tables import ReadingSessionsTable

    row = ReadingSessionsTable(game_key="42", game_name="NEKOPARA vol.1", start_ts=1.0)
    row.save()
    other = ReadingSessionsTable(game_key="43", game_name="Other", start_ts=1.0)
    other.save()
    res = client.post("/api/review/sessions/end", json={"game_name": "NEKOPARA vol.1"})
    assert res.status_code == 200 and [r["id"] for r in res.json["closed"]] == [row.id]
    assert ReadingSessionsTable.get(row.id).status == "closed"
    assert ReadingSessionsTable.get(other.id).status == "open"
