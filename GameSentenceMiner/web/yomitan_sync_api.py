"""Firefox Yomitan export → overlay Yomitan (see util/yomitan_sync.py).

Routes (localhost only):
  GET  /api/yomitan-sync/status             exports found, overlay connection, last results, import progress
  POST /api/yomitan-sync/sync               {kind: all|settings|dictionaries}
  GET  /api/yomitan-sync/dictionaries-file  the dictionary export, fetched by the overlay's Yomitan
"""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import jsonify, request, send_file

from GameSentenceMiner.util import yomitan_sync
from GameSentenceMiner.util.config.configuration import logger

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _is_loopback() -> bool:
    return (request.remote_addr or "") in _LOOPBACK


def _same_origin_local() -> bool:
    origin = request.headers.get("Origin")
    host_is_local = urlsplit(request.host_url).hostname in _LOOPBACK
    same_origin = not origin or origin.rstrip("/") == request.host_url.rstrip("/")
    return _is_loopback() and host_is_local and same_origin and request.headers.get("Sec-Fetch-Site") != "cross-site"


def _export_info(export):
    if not export:
        return None
    return {k: export[k] for k in ("name", "date", "hash", "size", "fingerprint") if k in export}


def register_yomitan_sync_routes(app):
    @app.route("/api/yomitan-sync/status", methods=["GET"])
    def yomitan_sync_status():
        if not _is_loopback():
            return jsonify({"error": "localhost only"}), 403
        try:
            settings = yomitan_sync.settings_export()
            settings_error = ""
        except yomitan_sync.YomitanSyncError as exc:
            settings, settings_error = None, str(exc)
        return jsonify(
            {
                "sync_dir": str(yomitan_sync.sync_dir()),
                "settings_export": _export_info(settings),
                "settings_error": settings_error,
                "dictionaries_export": _export_info(yomitan_sync.dictionaries_export()),
                "overlay_connected": yomitan_sync._overlay_connected(),
                "state": yomitan_sync.get_state(),
            }
        ), 200

    @app.route("/api/yomitan-sync/sync", methods=["POST"])
    def yomitan_sync_now():
        if not _same_origin_local():
            return jsonify({"error": "localhost only"}), 403
        kind = str((request.get_json(silent=True) or {}).get("kind") or "all")
        try:
            if kind == "settings":
                result = {"settings": yomitan_sync._summary(yomitan_sync.sync_settings())}
            elif kind == "dictionaries":
                result = {"dictionaries": yomitan_sync.start_dictionary_import()}
            elif kind == "all":
                result = yomitan_sync.sync_all()
            else:
                return jsonify({"error": "kind must be all, settings or dictionaries"}), 400
        except yomitan_sync.YomitanSyncError as exc:
            return jsonify({"error": str(exc)}), 409
        status = 202 if "dictionaries" in result else 200
        return jsonify(result), status

    @app.route("/api/yomitan-sync/dictionaries-file", methods=["GET"])
    def yomitan_sync_dictionaries_file():
        if not _is_loopback():
            return jsonify({"error": "localhost only"}), 403
        export = yomitan_sync.dictionaries_export()
        if export is None:
            return jsonify({"error": "No dictionary export found"}), 404
        logger.info(f"Serving {export['name']} to the overlay Yomitan ({export['size']} bytes).")
        return send_file(export["path"], mimetype="application/json", conditional=True, max_age=0)
