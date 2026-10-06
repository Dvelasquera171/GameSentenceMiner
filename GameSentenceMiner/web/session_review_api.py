"""Session review API: list reading sessions, generate an AI review in the background, grade answers live.

Routes (all localhost Flask):
  GET  /review                                  page
  GET  /api/review/games                        games that have lines (game_key, name, counts)
  GET  /api/review/sessions?game_key=&limit=    auto + manual sessions for a game, newest first
  GET  /api/review/sessions/open                open manual sessions
  POST /api/review/sessions/start               {game_key?, game_name?}  (defaults to current game)
  POST /api/review/sessions/end                 {session_id?} | {game_key?}
  POST /api/review/generate                     {game_key, start_ts, end_ts, question_count?} -> 202 {review_id}
  GET  /api/review/reviews?game_key=&limit=     stored reviews (without quiz bodies)
  GET  /api/review/reviews/<id>                 full review incl. status/stage while running
  POST /api/review/reviews/<id>/grade           {question_id, answer} -> grade (live AI call)
  GET  /api/review/reviews/<id>/attempts        graded attempts so far
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

from flask import jsonify, render_template, request

from GameSentenceMiner.ai.features.session_review import (
    QuizQuestion,
    ReviewLine,
    SessionReviewError,
    build_generator,
)
from GameSentenceMiner.ai.setup import ai_error_message, ai_setup_required
from GameSentenceMiner.util import reading_sessions
from GameSentenceMiner.util.config.configuration import get_config, logger
from GameSentenceMiner.util.database.db import GameLinesTable
from GameSentenceMiner.util.database.session_review_tables import (
    REVIEW_STATUS_DONE,
    REVIEW_STATUS_FAILED,
    REVIEW_STATUS_RUNNING,
    SessionQuizAttemptsTable,
    SessionReviewsTable,
)

_jobs_lock = threading.Lock()
_running_jobs: set = set()


def _current_game_key_and_name() -> tuple[str, str]:
    from GameSentenceMiner.obs import get_current_game
    from GameSentenceMiner.util.database.games_table import GamesTable

    name = str(get_current_game() or "").strip()
    if not name:
        return "", ""
    game = GamesTable.get_or_create_by_name(name)
    return str(getattr(game, "id", "") or name), name


GRADE_CONTEXT_LINES = 3


def _quiz_question(raw_question: dict, question_id: str) -> QuizQuestion:
    return QuizQuestion(
        id=question_id,
        kind=str(raw_question.get("kind") or ""),
        question_ja=str(raw_question.get("question_ja") or ""),
        hint_ja=str(raw_question.get("hint_ja") or ""),
        reference_answer_ja=str(raw_question.get("reference_answer_ja") or ""),
        reference_answer_en=str(raw_question.get("reference_answer_en") or ""),
        rubric_en=list(raw_question.get("rubric_en") or []),
        source_line_ids=[str(x) for x in (raw_question.get("source_line_ids") or [])],
    )


def _grading_lines(review: SessionReviewsTable, line_ids: List[str], radius: int = GRADE_CONTEXT_LINES):
    """The quoted lines plus a few around each: the grader needs the scene, not one line."""
    wanted = {str(lid) for lid in line_ids}
    session = reading_sessions.get_session_lines(review.game_key, review.start_ts, review.end_ts)
    positions = [i for i, row in enumerate(session) if str(row.id) in wanted]
    if not positions:
        rows = (GameLinesTable.get(lid) for lid in line_ids)
        return [ReviewLine.from_game_line(row) for row in rows if row is not None]
    keep = sorted({j for p in positions for j in range(max(0, p - radius), min(len(session), p + radius + 1))})
    return [ReviewLine.from_game_line(session[j]) for j in keep]


def _review_lines(review: SessionReviewsTable) -> List[ReviewLine]:
    rows = reading_sessions.get_session_lines(review.game_key, review.start_ts, review.end_ts)
    return [ReviewLine.from_game_line(r) for r in rows]


def run_review_job(review_id: int, question_count: Optional[int] = None) -> None:
    """Thread body. Everything the page polls for lives on the review row."""
    review = SessionReviewsTable.get(review_id)
    if review is None:
        return
    try:
        review.set_stage("loading", "")
        lines = _review_lines(review)
        generator = build_generator(logger)
        review.provider = generator.ai.config_snapshot.ai.provider
        review.model = generator.ai._get_model_for_provider(generator.ai.config_snapshot.ai)

        def progress(stage: str, detail: str) -> None:
            review.set_stage(stage, detail)

        result = generator.run(
            lines, review.game_name or review.game_key, progress=progress, question_count=question_count
        )
        payload = result.to_dict()
        review.summary_ja = payload["summary_ja"]
        review.summary_en = payload["summary_en"]
        review.quiz = payload["quiz"]
        review.highlights = {
            "items": payload["highlights"],
            "characters": payload["characters"],
            "may_have_missed_ja": payload["may_have_missed_ja"],
            "may_have_missed_en": payload["may_have_missed_en"],
        }
        review.line_count = result.line_count
        review.char_count = result.char_count
        review.status = REVIEW_STATUS_DONE
        review.stage = "done"
        review.progress = ""
        review.updated_at = time.time()
        review.save()
        logger.info(f"Session review {review_id} finished: {len(result.quiz)} questions, {result.char_count} chars")
    except Exception as exc:  # the row is the error channel; the page shows it
        logger.error(f"Session review {review_id} failed: {exc}", exc_info=True)
        review.mark_failed(ai_error_message(exc) if not isinstance(exc, SessionReviewError) else str(exc))
    finally:
        with _jobs_lock:
            _running_jobs.discard(review_id)


def start_review_job(review_id: int, question_count: Optional[int] = None, runner=run_review_job) -> bool:
    with _jobs_lock:
        if review_id in _running_jobs:
            return False
        _running_jobs.add(review_id)
    threading.Thread(
        target=runner, args=(review_id, question_count), name=f"session-review-{review_id}", daemon=True
    ).start()
    return True


def _float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def register_session_review_routes(app):
    @app.route("/review")
    def review_page():
        return render_template("review.html", config=get_config())

    @app.route("/api/review/games", methods=["GET"])
    def review_games():
        rows = GameLinesTable._db.fetchall(
            f"SELECT game_id, game_name, COUNT(*), MAX(timestamp), SUM(LENGTH(line_text)) "
            f"FROM {GameLinesTable._table} GROUP BY game_id, game_name ORDER BY MAX(timestamp) DESC"
        )
        games = [
            {
                "game_key": (r[0] or r[1] or ""),
                "game_name": r[1] or "",
                "line_count": int(r[2] or 0),
                "last_ts": _float(r[3], 0.0),
                "char_count": int(r[4] or 0),
            }
            for r in rows
            if (r[0] or r[1])
        ]
        return jsonify({"games": games}), 200

    @app.route("/api/review/sessions", methods=["GET"])
    def review_sessions():
        game_key = str(request.args.get("game_key") or "").strip()
        if not game_key:
            return jsonify({"error": "game_key is required"}), 400
        limit = int(request.args.get("limit") or 50)
        sessions = reading_sessions.list_sessions(game_key, limit=limit)
        return jsonify({"sessions": [s.to_dict() for s in sessions]}), 200

    @app.route("/api/review/sessions/open", methods=["GET"])
    def review_open_sessions():
        from GameSentenceMiner.util.database.session_review_tables import ReadingSessionsTable

        rows = ReadingSessionsTable.get_open()
        return jsonify({"sessions": [vars(r) for r in rows]}), 200

    @app.route("/api/review/sessions/start", methods=["POST"])
    def review_start_session():
        data = request.get_json(silent=True) or {}
        game_key = str(data.get("game_key") or "").strip()
        game_name = str(data.get("game_name") or "").strip()
        if not game_key:
            game_key, game_name = _current_game_key_and_name()
        if not game_key:
            return jsonify({"error": "No game selected and no current game detected."}), 400
        session = reading_sessions.start_manual_session(game_key, game_name)
        return jsonify({"session": vars(session)}), 201

    @app.route("/api/review/sessions/end", methods=["POST"])
    def review_end_session():
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        game_key = str(data.get("game_key") or "").strip() or None
        game_name = str(data.get("game_name") or "").strip()
        if session_id is None and game_key is None and game_name:
            # Desktop automation knows the game by its OBS scene name only.
            closed = reading_sessions.end_sessions_for_game(game_name)
            return jsonify({"closed": [vars(r) for r in closed]}), 200
        if session_id is None and game_key is None:
            game_key, _ = _current_game_key_and_name()
            game_key = game_key or None
        closed = reading_sessions.end_manual_session(
            session_id=int(session_id) if session_id is not None else None, game_key=game_key
        )
        return jsonify({"closed": [vars(r) for r in closed]}), 200

    @app.route("/api/review/sessions/toggle", methods=["POST"])
    def review_toggle_session():
        """Overlay session hotkey: End when the current game has an open session, else Start."""
        data = request.get_json(silent=True) or {}
        game_key = str(data.get("game_key") or "").strip()
        game_name = str(data.get("game_name") or "").strip()
        if not game_key:
            game_key, game_name = _current_game_key_and_name()
        if not game_key:
            return jsonify({"error": "No game selected and no current game detected."}), 400
        action, rows = reading_sessions.toggle_manual_session(game_key, game_name)
        return jsonify({"action": action, "game_name": game_name, "sessions": [vars(r) for r in rows]}), 200

    @app.route("/api/review/session-lines", methods=["GET"])
    def review_session_lines():
        """Lines of one session, so the page can show them and delete them via /api/delete-sentence-lines."""
        game_key = str(request.args.get("game_key") or "").strip()
        start_ts, end_ts = _float(request.args.get("start_ts")), _float(request.args.get("end_ts"))
        if not game_key or start_ts is None or end_ts is None or end_ts < start_ts:
            return jsonify({"error": "game_key, start_ts and end_ts are required"}), 400
        lines = reading_sessions.get_session_lines(game_key, start_ts, end_ts)
        return jsonify(
            {
                "lines": [
                    {"id": str(ln.id), "timestamp": _float(ln.timestamp, 0.0), "text": str(ln.line_text or "")}
                    for ln in lines
                ],
                "char_count": sum(len(ln.line_text or "") for ln in lines),
            }
        ), 200

    @app.route("/api/review/sessions/<int:session_id>/delete", methods=["POST"])
    def review_delete_session_mark(session_id: int):
        """Remove a manual Start/End mark. The lines stay; they fall back into automatic sessions."""
        from GameSentenceMiner.util.database.session_review_tables import ReadingSessionsTable

        row = ReadingSessionsTable.get(session_id)
        if row is None:
            return jsonify({"error": "Session not found"}), 404
        row.delete()
        return jsonify({"deleted": session_id}), 200

    @app.route("/api/review/generate", methods=["POST"])
    def review_generate():
        data = request.get_json(silent=True) or {}
        game_key = str(data.get("game_key") or "").strip()
        start_ts, end_ts = _float(data.get("start_ts")), _float(data.get("end_ts"))
        if not game_key or start_ts is None or end_ts is None or end_ts < start_ts:
            return jsonify({"error": "game_key, start_ts and end_ts are required"}), 400
        if not get_config().ai.is_configured():
            return jsonify(ai_setup_required(automatic=False)), 400
        lines = reading_sessions.get_session_lines(game_key, start_ts, end_ts)
        if not lines:
            return jsonify({"error": "No lines in that range"}), 404
        question_count = data.get("question_count")
        review = SessionReviewsTable(
            game_key=game_key,
            game_name=str(data.get("game_name") or getattr(lines[0], "game_name", "") or ""),
            start_ts=start_ts,
            end_ts=end_ts,
            line_count=len(lines),
            char_count=sum(len(ln.line_text or "") for ln in lines),
            status=REVIEW_STATUS_RUNNING,
            stage="queued",
        )
        review.save()
        start_review_job(review.id, int(question_count) if question_count is not None else None)
        return jsonify({"review_id": review.id, "status": review.status}), 202

    @app.route("/api/review/reviews", methods=["GET"])
    def review_list():
        game_key = str(request.args.get("game_key") or "").strip() or None
        limit = int(request.args.get("limit") or 50)
        rows = SessionReviewsTable.list_recent(game_key, limit=limit)
        items = []
        for r in rows:
            d = r.to_dict()
            d["question_count"] = len(r.quiz or [])
            d.pop("quiz", None)
            d.pop("highlights", None)
            d.pop("summary_en", None)
            items.append(d)
        return jsonify({"reviews": items}), 200

    @app.route("/api/review/reviews/<int:review_id>", methods=["GET"])
    def review_get(review_id: int):
        review = SessionReviewsTable.get(review_id)
        if review is None:
            return jsonify({"error": "Review not found"}), 404
        return jsonify(review.to_dict()), 200

    @app.route("/api/review/reviews/<int:review_id>/attempts", methods=["GET"])
    def review_attempts(review_id: int):
        return jsonify({"attempts": [vars(a) for a in SessionQuizAttemptsTable.for_review(review_id)]}), 200

    @app.route("/api/review/reviews/<int:review_id>/grade", methods=["POST"])
    def review_grade(review_id: int):
        data = request.get_json(silent=True) or {}
        question_id = str(data.get("question_id") or "").strip()
        answer = str(data.get("answer") or "").strip()
        if not question_id or not answer or len(answer) > 4000:
            return jsonify({"error": "question_id and an answer of 1-4000 characters are required"}), 400
        review = SessionReviewsTable.get(review_id)
        if review is None or review.status != REVIEW_STATUS_DONE:
            return jsonify({"error": "Review not ready"}), 404
        raw_question = next((q for q in review.quiz if str(q.get("id")) == question_id), None)
        if raw_question is None:
            return jsonify({"error": "Unknown question"}), 404
        if not get_config().ai.is_configured():
            return jsonify(ai_setup_required(automatic=False)), 400
        question = _quiz_question(raw_question, question_id)
        source_lines = _grading_lines(review, question.source_line_ids)
        try:
            grade = build_generator(logger).grade_answer(question, answer, source_lines, review.game_name)
        except Exception as exc:
            return jsonify({"error": ai_error_message(exc), "code": "ai_request_failed"}), 502
        attempt = SessionQuizAttemptsTable(
            review_id=review_id, question_id=question_id, answer=answer, grade=vars(grade)
        )
        attempt.save()
        return jsonify({"grade": vars(grade), "attempt_id": attempt.id}), 200

    @app.route("/api/review/reviews/<int:review_id>/attempts/<int:attempt_id>/discuss", methods=["POST"])
    def review_discuss(review_id: int, attempt_id: int):
        """質問・異議: the learner asks about a grade; the AI replies and may revise it."""
        message = str((request.get_json(silent=True) or {}).get("message") or "").strip()
        if not message or len(message) > 2000:
            return jsonify({"error": "A message of 1-2000 characters is required"}), 400
        review = SessionReviewsTable.get(review_id)
        attempt = SessionQuizAttemptsTable.get(attempt_id)
        if review is None or attempt is None or attempt.review_id != review_id:
            return jsonify({"error": "Answer not found"}), 404
        raw_question = next((q for q in review.quiz if str(q.get("id")) == attempt.question_id), None)
        if raw_question is None:
            return jsonify({"error": "Unknown question"}), 404
        if not get_config().ai.is_configured():
            return jsonify(ai_setup_required(automatic=False)), 400
        question = _quiz_question(raw_question, attempt.question_id)
        grade = dict(attempt.grade or {})
        history = list(grade.get("discussion") or [])
        try:
            result = build_generator(logger).discuss_grade(
                question,
                attempt.answer,
                grade,
                [{"message": d.get("message"), "reply_ja": d.get("reply_ja")} for d in history],
                message,
                _grading_lines(review, question.source_line_ids),
                review.game_name,
            )
        except Exception as exc:
            return jsonify({"error": ai_error_message(exc), "code": "ai_request_failed"}), 502
        revised = result.get("revised")
        if revised:
            grade.setdefault("original", {"verdict": grade.get("verdict"), "score": grade.get("score")})
            grade.update(revised)
        history.append(
            {
                "message": message,
                "reply_ja": result.get("reply_ja", ""),
                "reply_en": result.get("reply_en", ""),
                "revised": revised,
                "at": time.time(),
            }
        )
        grade["discussion"] = history
        attempt.grade = grade
        attempt.save()
        return jsonify({"grade": grade, "attempt_id": attempt.id}), 200

    # Exposed for tests and for a future "retry failed review" button.
    app.config.setdefault("SESSION_REVIEW_STATUSES", (REVIEW_STATUS_RUNNING, REVIEW_STATUS_DONE, REVIEW_STATUS_FAILED))
