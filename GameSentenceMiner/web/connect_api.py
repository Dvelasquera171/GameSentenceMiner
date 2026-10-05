"""GSM Connect: subtitle and manga lines from the browser extension (gsm_connect/).

Routes:
  GET  /api/connect/status  {ok, last: {at, title, site} | null}
  POST /api/connect/lines   {lines: [{text, title, source, url, captured_at}]} -> {results: [status, ...]}

Each line is filed under its own title (the video, anime or manga), never the current game, and
cards mined from these lines keep the media the browser made (see anki.update_single_card).
The extension queues lines while GSM is closed, so captured_at can be hours old.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from flask import jsonify, request

from GameSentenceMiner.util.config.configuration import logger

MAX_LINES_PER_REQUEST = 500
SITE_NAMES = {
    "youtube": "YouTube",
    "asbplayer": "asbplayer",
    "manatan": "Manatan",
    "manatan-manga": "Manatan",
    "netflix": "Netflix",
    "mokuro": "mokuro",
    "video": "Video",
}

_last_activity: dict = {}


def site_label(site: str) -> str:
    return SITE_NAMES.get(site, site.capitalize() if site else "Browser")


def build_ingest_payload(line) -> Optional[dict]:
    if not isinstance(line, dict):
        return None
    text = str(line.get("text") or "").strip()
    if not text:
        return None
    site = str(line.get("source") or "").strip().lower()[:40]
    title = str(line.get("title") or "").strip()[:200] or site_label(site)
    payload = {
        "text": text,
        "source": "browser",
        "source_display_name": f"GSM Connect · {site_label(site)}",
        "source_instance": f"connect:{site}:{title}",
        "title": title,
        "url": str(line.get("url") or "")[:500],
        # The in-game overlay shows game text; browser text stays in the browser.
        "skip_overlay": True,
    }
    if line.get("captured_at"):
        payload["captured_at"] = line["captured_at"]
    return payload


def last_activity() -> Optional[dict]:
    return dict(_last_activity) if _last_activity else None


def _default_ingest(payload: dict) -> dict:
    from GameSentenceMiner.gametext import ingest_text_v2_payload

    return ingest_text_v2_payload(payload)


def register_connect_routes(app, ingest: Optional[Callable[[dict], dict]] = None):
    @app.route("/api/connect/status", methods=["GET"])
    def connect_status():
        return jsonify({"ok": True, "last": last_activity()}), 200

    @app.route("/api/connect/lines", methods=["POST"])
    def connect_lines():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
            return jsonify({"error": "Expected {lines: [...]}"}), 400
        lines = data["lines"]
        if len(lines) > MAX_LINES_PER_REQUEST:
            return jsonify({"error": f"At most {MAX_LINES_PER_REQUEST} lines per request"}), 413

        ingest_fn = ingest or _default_ingest
        results = []
        for line in lines:
            payload = build_ingest_payload(line)
            if payload is None:
                results.append("rejected")
                continue
            try:
                status = str((ingest_fn(payload) or {}).get("status") or "rejected")
            except Exception:  # noqa: BLE001 - one bad line must not lose the rest of the batch
                logger.exception("GSM Connect: could not ingest a line")
                status = "backpressured"
            results.append(status)
            if status == "accepted":
                _last_activity.update(
                    {"at": time.time(), "title": payload["title"], "site": site_label(str(line.get("source") or ""))}
                )
        return jsonify({"results": results}), 200
