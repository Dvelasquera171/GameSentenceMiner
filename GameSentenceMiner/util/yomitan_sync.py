"""Firefox Yomitan export → overlay Yomitan.

The owner saves Firefox Yomitan's exports (Settings → Backup → Export Settings / Export Dictionary
Collection) into SYNC_DIR under their default names. GSM sends the settings to the running overlay,
which merges and applies them (GSM_Overlay/yomitan_sync.js), and asks it to import the dictionary
collection when that file changes. Firefox is the source of truth; nothing flows back.
"""
# File times are shown as local wall-clock values.
# ruff: noqa: DTZ006

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from GameSentenceMiner.util.config.configuration import get_config, logger
from GameSentenceMiner.util.data_directory import get_app_directory

SYNC_DIR_NAME = "yomitan_sync"
SETTINGS_PATTERNS = ("settings.json", "yomitan-settings-*.json")
DICTIONARY_PATTERNS = ("dictionaries.json", "yomitan-dictionaries-*.json")
WATCH_INTERVAL_SECONDS = 10
STATUS_MAX_AGE_SECONDS = 60
SETTINGS_TIMEOUT_SECONDS = 60
STATUS_TIMEOUT_SECONDS = 25
IMPORT_STALE_SECONDS = 60

EXPORT_STEPS = (
    "In Firefox: Yomitan → Settings → Backup → Export Settings, and (when dictionaries changed) "
    "Export Dictionary Collection. Save both files, keeping their names, into {dir}."
)


class YomitanSyncError(RuntimeError):
    pass


def sync_dir() -> Path:
    return Path(get_app_directory()) / SYNC_DIR_NAME


def _newest(patterns, directory: Path | None = None) -> Path | None:
    folder = directory or sync_dir()
    if not folder.is_dir():
        return None
    found = {p for pattern in patterns for p in folder.glob(pattern) if p.is_file()}
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def extract_export_options(data: Any) -> dict:
    """Same rule as the overlay: a full Yomitan export or the bare options object."""
    options = None
    if isinstance(data, dict):
        options = data["options"] if isinstance(data.get("options"), dict) else data
    if not isinstance(options, dict) or not isinstance(options.get("profiles"), list) or not options["profiles"]:
        raise YomitanSyncError("This file is not a Yomitan settings export (Settings → Backup → Export Settings).")
    return options


def current_profile(options: dict) -> dict:
    profiles = options.get("profiles") or [{}]
    index = options.get("profileCurrent") if isinstance(options.get("profileCurrent"), int) else 0
    return profiles[min(max(index, 0), len(profiles) - 1)] or {}


_settings_cache: dict[str, Any] = {"key": None, "value": None}


def settings_export(directory: Path | None = None) -> dict | None:
    path = _newest(SETTINGS_PATTERNS, directory)
    if path is None:
        return None
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if _settings_cache["key"] == key:
        return _settings_cache["value"]
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise YomitanSyncError(f"{path.name} is not valid JSON: {exc}") from exc
    options = extract_export_options(data)
    date = data.get("date") if isinstance(data, dict) and isinstance(data.get("date"), str) else ""
    value = {
        "path": str(path),
        "name": path.name,
        "hash": hashlib.sha256(raw).hexdigest(),
        "date": date or datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "options": options,
    }
    _settings_cache.update({"key": key, "value": value})
    return value


def dictionaries_export(directory: Path | None = None) -> dict | None:
    path = _newest(DICTIONARY_PATTERNS, directory)
    if path is None:
        return None
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "size": stat.st_size,
        "date": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        # Hashing a multi-GB file every few seconds is too slow; name + size + mtime is enough.
        "fingerprint": f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}",
    }


def normalize_card_formats(anki: Any) -> list[dict]:
    formats = anki.get("cardFormats") if isinstance(anki, dict) else None
    result = []
    for fmt in formats if isinstance(formats, list) else []:
        fmt = fmt if isinstance(fmt, dict) else {}
        fields = fmt.get("fields") if isinstance(fmt.get("fields"), dict) else {}
        result.append(
            {
                "name": str(fmt.get("name") or ""),
                "type": str(fmt.get("type") or ""),
                "deck": str(fmt.get("deck") or ""),
                "model": str(fmt.get("model") or ""),
                "fields": {
                    str(name): {
                        "value": str((field or {}).get("value") or ""),
                        "overwriteMode": str((field or {}).get("overwriteMode") or ""),
                    }
                    for name, field in fields.items()
                },
            }
        )
    return result


def compare_card_formats(expected: list[dict], actual: list[dict]) -> list[str]:
    """Field-by-field differences, worded like the overlay's own check."""
    diffs = []
    if len(expected) != len(actual):
        diffs.append(f"card format count: Firefox {len(expected)}, overlay {len(actual)}")
    for i, (a, b) in enumerate(zip(expected, actual)):
        label = f"card format {i + 1} ({a['name'] or a['type']})"
        for key in ("name", "type", "deck", "model"):
            if a[key] != b.get(key, ""):
                diffs.append(f'{label} {key}: Firefox "{a[key]}", overlay "{b.get(key, "")}"')
        other_fields = b.get("fields") or {}
        for field, value in a["fields"].items():
            other = other_fields.get(field)
            if other is None:
                diffs.append(f"{label} field {field}: missing in the overlay")
                continue
            for key in ("value", "overwriteMode"):
                if value[key] != other.get(key, ""):
                    diffs.append(f'{label} field {field} {key}: Firefox "{value[key]}", overlay "{other.get(key, "")}"')
        for field in other_fields:
            if field not in a["fields"]:
                diffs.append(f"{label} field {field}: only in the overlay")
    return diffs


# ---------------------------------------------------------------------------
# Overlay messaging
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_pending: dict[str, tuple] = {}
_seen_results: list[str] = []
_state: dict[str, Any] = {
    "status": None,
    "status_at": 0.0,
    "status_error": "",
    "progress": None,
    "results": {},
    "dictionary_job": {"running": False, "request_id": "", "started_at": 0.0},
}


def _overlay_connected() -> bool:
    from GameSentenceMiner.web.gsm_websocket import ID_OVERLAY, websocket_manager

    return websocket_manager.has_clients(ID_OVERLAY)


def _send_to_overlay(message: dict) -> None:
    from GameSentenceMiner.web.gsm_websocket import ID_OVERLAY, websocket_manager

    websocket_manager.send_nowait(ID_OVERLAY, message)


def _request(message_type: str, data: dict, timeout: float, wait: bool = True) -> dict:
    if not _overlay_connected():
        raise YomitanSyncError("Start the GSM overlay (with Yomitan as its dictionary), then retry.")
    request_id = str(uuid.uuid4())
    event = threading.Event()
    result: dict = {}
    if wait:
        with _lock:
            _pending[request_id] = (event, result)
    try:
        _send_to_overlay(
            {
                "type": message_type,
                "request_id": request_id,
                "deadline": int((time.time() + timeout - 1) * 1000),
                "data": data,
            }
        )
        if not wait:
            return {"request_id": request_id}
        if not event.wait(timeout):
            raise YomitanSyncError("The overlay did not answer. Restart the overlay and retry.")
        return result
    finally:
        with _lock:
            _pending.pop(request_id, None)


def accept_overlay_message(message: dict) -> bool:
    """Called by the overlay websocket handler for yomitan-sync-* messages."""
    message_type = message.get("type")
    if message_type == "yomitan-sync-progress":
        with _lock:
            _state["progress"] = {**message, "at": time.time()}
        return True
    if message_type != "yomitan-sync-result":
        return False
    request_id = str(message.get("request_id") or "")
    kind = message.get("kind")
    with _lock:
        pending = _pending.get(request_id)
        if pending is not None:
            pending[1].update(message)
            pending[0].set()
        # The overlay answers on both of its connections; record each result once.
        if request_id in _seen_results:
            return True
        _seen_results.append(request_id)
        del _seen_results[:-64]
        _state["results"][kind] = {**message, "at": time.time()}
        if message.get("success") and "cardFormats" in message:
            _state["status"] = message
            _state["status_at"] = time.time()
            _state["status_error"] = ""
        elif kind == "status" and not message.get("success"):
            _state["status_error"] = str(message.get("error") or "")
        follow_up = False
        if kind == "dictionaries":
            _state["dictionary_job"] = {"running": False, "request_id": "", "started_at": 0.0}
            _state["progress"] = None
            follow_up = bool(message.get("success"))
        elif _import_was_interrupted(message):
            _clear_interrupted_import()
    if follow_up:
        # Dictionary entries in the settings refer to installed dictionaries; re-apply them now.
        threading.Thread(target=_sync_settings_quietly, name="yomitan-sync-after-import", daemon=True).start()
    return True


def _import_was_interrupted(message: dict) -> bool:
    """GSM thinks an import runs, but the overlay that answered is not importing (it was closed or restarted)."""
    busy = message.get("busy")
    return (
        _state["dictionary_job"]["running"]
        and isinstance(busy, dict)
        and not busy.get("dictionaries")
        and time.time() - _state["dictionary_job"]["started_at"] > 1
    )


def _clear_interrupted_import() -> None:
    # Caller holds _lock.
    logger.warning("Overlay Yomitan dictionary import was interrupted (overlay closed); it will be retried.")
    _state["dictionary_job"] = {"running": False, "request_id": "", "started_at": 0.0}
    _state["progress"] = None
    _state["results"]["dictionaries"] = {
        "kind": "dictionaries",
        "success": False,
        "error": "The dictionary import was interrupted because the overlay closed. It restarts automatically.",
        "at": time.time(),
    }
    export = dictionaries_export()
    if export is not None:
        _watch["attempted"].discard(export["fingerprint"])


def _sync_settings_quietly() -> None:
    try:
        if settings_export() is not None:
            sync_settings()
    except Exception as exc:  # noqa: BLE001 - background follow-up; logged, never raised
        logger.warning(f"Yomitan settings sync after dictionary import failed: {exc}")


def sync_settings(timeout: float = SETTINGS_TIMEOUT_SECONDS) -> dict:
    export = settings_export()
    if export is None:
        raise YomitanSyncError("No Firefox settings export found. " + EXPORT_STEPS.format(dir=sync_dir()))
    result = _request(
        "yomitan-sync-settings",
        {
            "settings": export["options"],
            "settings_hash": export["hash"],
            "export_date": export["date"],
            "export_name": export["name"],
        },
        timeout,
    )
    if not result.get("success"):
        raise YomitanSyncError(result.get("error") or "The overlay could not apply the Yomitan settings.")
    logger.info(f"Overlay Yomitan synced from {export['name']} ({export['date']}).")
    return result


def start_dictionary_import() -> dict:
    export = dictionaries_export()
    if export is None:
        raise YomitanSyncError("No dictionary collection export found. " + EXPORT_STEPS.format(dir=sync_dir()))
    with _lock:
        if _state["dictionary_job"]["running"]:
            raise YomitanSyncError("A dictionary import is already running in the overlay.")
    port = get_config().general.single_port
    started = _request(
        "yomitan-sync-dictionaries",
        {
            "url": f"http://127.0.0.1:{port}/api/yomitan-sync/dictionaries-file",
            "size": export["size"],
            "fingerprint": export["fingerprint"],
            "export_name": export["name"],
        },
        SETTINGS_TIMEOUT_SECONDS,
        wait=False,
    )
    with _lock:
        _state["dictionary_job"] = {"running": True, "request_id": started["request_id"], "started_at": time.time()}
        _state["progress"] = None
    logger.info(f"Overlay Yomitan dictionary import started from {export['name']} ({export['size']} bytes).")
    return {"started": True, "export": {k: export[k] for k in ("name", "size", "date")}}


def request_status(timeout: float = STATUS_TIMEOUT_SECONDS) -> dict:
    result = _request("yomitan-sync-status-request", {}, timeout)
    if not result.get("success"):
        raise YomitanSyncError(result.get("error") or "The overlay could not report its Yomitan settings.")
    return result


def overlay_status(max_age: float = STATUS_MAX_AGE_SECONDS) -> dict | None:
    """Recent overlay report, refreshed when older than max_age. None when the overlay is not running."""
    if not _overlay_connected():
        return None
    with _lock:
        cached, at = _state["status"], _state["status_at"]
    if cached is not None and time.time() - at < max_age:
        return cached
    try:
        return request_status()
    except YomitanSyncError as exc:
        with _lock:
            _state["status_error"] = str(exc)
        raise


def needs_sync(status: dict | None) -> dict[str, bool]:
    last = (status or {}).get("lastSync") or {}
    settings = settings_export()
    dictionaries = dictionaries_export()
    return {
        "settings": bool(settings and settings["hash"] != (last.get("settings") or {}).get("hash")),
        "dictionaries": bool(
            dictionaries and dictionaries["fingerprint"] != (last.get("dictionaries") or {}).get("hash")
        ),
    }


def sync_all() -> dict:
    """Import dictionaries when that export changed (settings follow automatically), else sync settings."""
    status = overlay_status(max_age=0)
    pending = needs_sync(status)
    if pending["dictionaries"]:
        return {"dictionaries": start_dictionary_import()}
    if settings_export() is None:
        raise YomitanSyncError("No Firefox settings export found. " + EXPORT_STEPS.format(dir=sync_dir()))
    return {"settings": _summary(sync_settings())}


def _summary(result: dict) -> dict:
    return {
        "profileName": result.get("profileName"),
        "missingDictionaries": result.get("missingDictionaries") or [],
        "cardFormats": len(result.get("cardFormats") or []),
    }


def get_state() -> dict:
    with _lock:
        state = json.loads(json.dumps(_state, default=str))
    for key in ("settings", "dictionaries"):
        state["results"].get(key, {}).pop("settings", None)
    return state


# ---------------------------------------------------------------------------
# Folder watcher
# ---------------------------------------------------------------------------

_watch = {"connected": False, "status_failed": False, "attempted": set(), "thread": None, "stop": threading.Event()}


def watch_once() -> str | None:
    """One watcher tick. Returns what it started ("dictionaries", "settings") or None."""
    if not _overlay_connected():
        _watch["connected"] = False
        return None
    if settings_export() is None and dictionaries_export() is None:
        return None
    newly_connected = not _watch["connected"]
    _watch["connected"] = True
    if newly_connected:
        _watch["status_failed"] = False
    elif _watch["status_failed"]:
        return None  # retry after the overlay reconnects, or via Sync now
    with _lock:
        job, progress = dict(_state["dictionary_job"]), dict(_state["progress"] or {})
    # A running import that has gone quiet may have died with its overlay; a fresh status settles it.
    last_heard = max(job["started_at"], float(progress.get("at") or 0))
    stale_import = job["running"] and time.time() - last_heard > IMPORT_STALE_SECONDS
    try:
        max_age = 0 if newly_connected else (IMPORT_STALE_SECONDS if stale_import else float("inf"))
        status = overlay_status(max_age=max_age)
    except YomitanSyncError as exc:
        _watch["status_failed"] = True
        logger.debug(f"Yomitan sync: overlay status unavailable: {exc}")
        return None
    with _lock:
        if _state["dictionary_job"]["running"]:
            return None
    pending = needs_sync(status)
    attempted = _watch["attempted"]
    dictionaries = dictionaries_export()
    if pending["dictionaries"] and dictionaries["fingerprint"] not in attempted:
        attempted.add(dictionaries["fingerprint"])
        start_dictionary_import()
        return "dictionaries"
    settings = settings_export()
    if pending["settings"] and settings["hash"] not in attempted:
        attempted.add(settings["hash"])
        try:
            sync_settings()
        except YomitanSyncError as exc:
            logger.warning(f"Automatic overlay Yomitan sync failed: {exc}")
        return "settings"
    return None


def _watch_loop() -> None:
    while not _watch["stop"].wait(WATCH_INTERVAL_SECONDS):
        try:
            watch_once()
        except Exception as exc:  # noqa: BLE001 - the watcher must survive bad files and overlay restarts
            logger.debug(f"Yomitan sync watcher tick failed: {exc}")


def start_watcher() -> threading.Thread:
    thread = _watch["thread"]
    if thread is not None and thread.is_alive():
        return thread
    _watch["stop"].clear()
    thread = threading.Thread(target=_watch_loop, name="yomitan-sync-watcher", daemon=True)
    _watch["thread"] = thread
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Setup page rows
# ---------------------------------------------------------------------------


def _sentence(text: str) -> str:
    return (text[:1].upper() + text[1:] + ".") if text else ""


SYNC_ACTION = {"label": "Sync now", "method": "POST", "url": "/api/yomitan-sync/sync", "body": {"kind": "all"}}


def setup_checks() -> list:
    from GameSentenceMiner.web.setup_check_api import (
        STATUS_FAIL,
        STATUS_OK,
        STATUS_SKIP,
        STATUS_WARN,
        Check,
    )

    sync_title, cards_title = "Overlay Yomitan: synced from Firefox", "Overlay Yomitan: Anki card formats match Firefox"
    steps = EXPORT_STEPS.format(dir=sync_dir())
    try:
        settings = settings_export()
    except YomitanSyncError as exc:
        return [
            Check("overlay_yomitan_sync", sync_title, STATUS_FAIL, str(exc), steps),
            Check("overlay_yomitan_cards", cards_title, STATUS_SKIP, "The settings export could not be read."),
        ]
    dictionaries = dictionaries_export()
    if settings is None:
        detail = f"No Firefox settings export in {sync_dir()}."
        if dictionaries:
            detail += f" A dictionary export is there ({dictionaries['name']})."
        return [
            Check("overlay_yomitan_sync", sync_title, STATUS_WARN, detail, steps),
            Check("overlay_yomitan_cards", cards_title, STATUS_SKIP, "No Firefox settings export to compare against."),
        ]

    export_label = f"{settings['name']} ({settings['date']})"
    try:
        status = overlay_status()
    except YomitanSyncError as exc:
        return [
            Check(
                "overlay_yomitan_sync",
                sync_title,
                STATUS_WARN,
                f"Export {export_label} found, but the overlay did not report its Yomitan settings: {exc}",
                "Start the GSM overlay with Yomitan as its dictionary, then press Re-check.",
            ),
            Check("overlay_yomitan_cards", cards_title, STATUS_SKIP, "Overlay status unavailable."),
        ]
    if status is None:
        return [
            Check(
                "overlay_yomitan_sync",
                sync_title,
                STATUS_SKIP,
                f"Export {export_label} found. The overlay is not running, so it cannot be checked.",
                "Start the GSM overlay, then press Re-check.",
            ),
            Check("overlay_yomitan_cards", cards_title, STATUS_SKIP, "The overlay is not running."),
        ]

    last = status.get("lastSync") or {}
    pending = needs_sync(status)
    with _lock:
        job = dict(_state["dictionary_job"])
        progress = dict(_state["progress"] or {})
    firefox_dicts = [
        d.get("name") for d in current_profile(settings["options"]).get("options", {}).get("dictionaries", [])
    ]
    installed = set(status.get("installed") or [])
    missing = [name for name in firefox_dicts if name and name not in installed]

    if job["running"]:
        done, total = progress.get("completedRows"), progress.get("totalRows")
        stage = progress.get("stage") or "starting"
        detail = f"Dictionary import running ({stage}" + (f", {done}/{total} rows" if total else "") + ")."
        sync_check = Check("overlay_yomitan_sync", sync_title, STATUS_WARN, detail, "Wait for it to finish.")
    elif pending["dictionaries"] or pending["settings"]:
        parts = []
        if pending["settings"]:
            applied = (last.get("settings") or {}).get("exportDate") or "never"
            parts.append(f"settings export {export_label} is newer than the overlay's last sync ({applied})")
        if pending["dictionaries"]:
            parts.append(f"dictionary export {dictionaries['name']} has not been imported yet")
        sync_check = Check(
            "overlay_yomitan_sync",
            sync_title,
            STATUS_WARN,
            _sentence("; ".join(parts)),
            "Press Sync now (here, or GSM Settings → Overlay). Dictionary imports can take several minutes.",
            action=SYNC_ACTION,
        )
    elif missing:
        sync_check = Check(
            "overlay_yomitan_sync",
            sync_title,
            STATUS_WARN,
            f"Synced from {export_label}, but the overlay lacks dictionaries Firefox uses: {', '.join(missing)}.",
            "In Firefox: Yomitan → Settings → Backup → Export Dictionary Collection into "
            f"{sync_dir()}, then press Sync now.",
            action=SYNC_ACTION,
        )
    else:
        sync_check = Check(
            "overlay_yomitan_sync",
            sync_title,
            STATUS_OK,
            f"Synced from {export_label} into overlay profile '{status.get('profileName')}'; "
            f"{len(firefox_dicts)} dictionaries present.",
        )

    expected = normalize_card_formats(current_profile(settings["options"]).get("options", {}).get("anki"))
    actual = status.get("cardFormats") or []
    diffs = compare_card_formats(expected, actual)
    firefox_anki = (current_profile(settings["options"]).get("options") or {}).get("anki") or {}
    if firefox_anki.get("enable") and not status.get("ankiEnabled", True):
        diffs.insert(0, "Anki is enabled in Firefox Yomitan but disabled in the overlay")
    if diffs:
        shown = diffs[:8] + ([f"…and {len(diffs) - 8} more"] if len(diffs) > 8 else [])
        cards_check = Check(
            "overlay_yomitan_cards",
            cards_title,
            STATUS_FAIL,
            "Overlay cards would differ from Firefox cards: " + "; ".join(shown) + ".",
            "Press Sync now. If it still differs, export settings from Firefox again.",
            action=SYNC_ACTION,
        )
    else:
        used = [f for f in expected if f["model"]]
        summary = ", ".join(f"{f['name']} → {f['deck']} / {f['model']} ({len(f['fields'])} fields)" for f in used)
        cards_check = Check(
            "overlay_yomitan_cards",
            cards_title,
            STATUS_OK,
            f"All {len(expected)} card formats identical, field by field" + (f": {summary}." if summary else "."),
        )
    return [sync_check, cards_check]
