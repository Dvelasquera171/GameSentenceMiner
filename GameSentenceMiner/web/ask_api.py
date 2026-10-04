"""In-game "Ask AI about this line" panel, opened by the overlay's AI hotkey (default Num0).

Routes:
  GET /ask                    the panel page (no navigation bar; Esc closes the overlay window)
  GET /api/ask/recent-lines   {game, lines: [{id, text, time}]} oldest to newest (?count=, default 30)

AI requests reuse POST /analyze-line, including its history and context_lines fields.
"""

from __future__ import annotations

from flask import jsonify, render_template, request

from GameSentenceMiner.util.config.configuration import logger

MAX_RECENT_LINES = 100


def recent_lines(lines, count: int) -> list:
    shown = [ln for ln in lines if str(getattr(ln, "text", "") or "").strip()][-count:]
    result = []
    for ln in shown:
        when = getattr(ln, "time", None)
        result.append(
            {
                "id": str(getattr(ln, "id", "")),
                "text": str(ln.text),
                "time": when.isoformat() if hasattr(when, "isoformat") else "",
            }
        )
    return result


def _current_game() -> str:
    try:
        from GameSentenceMiner.obs import get_current_game

        return str(get_current_game() or "")
    except Exception:  # noqa: BLE001 - the title is cosmetic; never fail the panel over it
        logger.debug("Ask panel: current game unavailable", exc_info=True)
        return ""


def register_ask_routes(app):
    @app.route("/ask")
    def ask_page():
        return render_template("ask.html")

    @app.route("/api/ask/recent-lines", methods=["GET"])
    def ask_recent_lines():
        from GameSentenceMiner.util.text_log import get_all_lines

        try:
            count = int(request.args.get("count") or 30)
        except ValueError:
            count = 30
        count = max(1, min(MAX_RECENT_LINES, count))
        return jsonify({"game": _current_game(), "lines": recent_lines(get_all_lines(), count)}), 200
