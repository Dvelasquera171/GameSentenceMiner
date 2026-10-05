"""Setup health page: one place to see whether text source → GSM → Anki → AI works.

Routes (localhost Flask):
  GET /setup-check                      page
  GET /api/setup-check[?ai_test=1]      {"checks": [...], "summary": {...}}

Each check is {id, title, status (ok|warn|fail|skip), detail, fix}. Every AnkiConnect call here
is read-only. The AI test call costs tokens, so it runs only with ai_test=1 (the page's
Re-check button), never on page load, and at most once per AI_TEST_COOLDOWN_SECONDS.
"""
# GSM status times and file times are local wall-clock values.
# ruff: noqa: DTZ005, DTZ007

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime

import requests
from flask import jsonify, render_template, request

from GameSentenceMiner.util.config.configuration import get_config, gsm_status, logger

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"

RECENT_LINE_SECONDS = 15 * 60
RECENT_NOTES_DAYS = 7
AI_TEST_COOLDOWN_SECONDS = 15
AI_TEST_MAX_TOKENS = 32
ANKI_TIMEOUT_SECONDS = 2.0

ANKI_FIELD_LABELS = {
    "word": "Word",
    "sentence": "Sentence",
    "sentence_audio": "Sentence audio",
    "picture": "Picture",
    "sentence_furigana": "Sentence furigana",
    "previous_sentence": "Previous sentence",
    "previous_image": "Previous image",
    "video": "Video",
    "game_name": "Game name",
}

ANKI_CONNECT_FIX = (
    "Start Anki. AnkiConnect must be installed (add-on 2055492159) and allow http://127.0.0.1:8765 "
    "(Tools → Add-ons → AnkiConnect → Config)."
)
AI_SETUP_FIX = "GSM Settings → AI: provider OpenAI, URL https://nano-gpt.com/api/v1, a model, and your API key."


@dataclass
class Check:
    id: str
    title: str
    status: str
    detail: str = ""
    fix: str = ""
    # Optional one-click fix rendered as a button: {label, method, url, body}.
    action: dict | None = None


class AnkiCallError(RuntimeError):
    pass


def _anki_call(action: str, timeout: float = ANKI_TIMEOUT_SECONDS, **params):
    """Plain AnkiConnect call; avoids anki.invoke's retry/error logging on every page load."""
    try:
        response = requests.post(
            get_config().anki.url,
            json={"action": action, "params": params, "version": 6},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise AnkiCallError(f"timed out after {timeout:g}s") from exc
    except requests.ConnectionError as exc:
        raise AnkiCallError("connection refused (is Anki running?)") from exc
    except Exception as exc:
        raise AnkiCallError(str(exc) or type(exc).__name__) from exc
    if not isinstance(payload, dict) or "result" not in payload:
        raise AnkiCallError("unexpected reply from AnkiConnect")
    if payload.get("error"):
        raise AnkiCallError(str(payload["error"]))
    return payload["result"]


# ---------------------------------------------------------------------------
# Text source checks
# ---------------------------------------------------------------------------


def _source_connected(uri: str, connected: dict[str, str]) -> bool:
    prefix = f"ws://{uri.strip()}"
    return any(str(key) == prefix or str(key).startswith(prefix + "/") for key in connected)


def check_text_sources(config, status: dict, inhouse: tuple[dict, dict] | None = None) -> list[Check]:
    general = config.general
    connected = status.get("websockets_connected") or {}
    if isinstance(connected, list):
        connected = {key: key for key in connected}
    sources = [s for s in (general.websocket_sources or []) if s.enabled and s.uri.strip()]
    listing = (
        ", ".join(
            f"{s.name or s.uri} ({s.uri}): {'connected' if _source_connected(s.uri, connected) else 'not connected'}"
            for s in sources
        )
        or "none"
    )
    inhouse, modes = _inhouse_sources() if inhouse is None else inhouse
    hook = bool(inhouse.get("texthook"))
    ocr = bool(inhouse.get("ocr"))
    ocr_mode = str(modes.get("ocr") or "")
    external = (
        [f"{s.name or s.uri} ({s.uri})" for s in sources if _source_connected(s.uri, connected)]
        if general.use_websocket
        else []
    )
    readers = (["GSM's built-in hook"] if hook else []) + external
    title = "Text source"
    start_fix = (
        "Start the game's hook: GSM → Texthook tab → choose the game and its hook (or start LunaTranslator / "
        "Agent if you use them). For a game that cannot be hooked, start OCR instead."
    )
    if not readers and not ocr:
        detail = "Nothing is reading text from a game."
        if sources:
            detail += f" Websocket sources GSM listens to: {listing}."
        source_check = Check("text_source", title, STATUS_FAIL, detail, start_fix)
    elif readers and ocr and ocr_mode != "manual":
        source_check = Check(
            "text_source",
            title,
            STATUS_WARN,
            f"Text comes from {', '.join(readers)}, and OCR is also scanning the screen continuously. "
            "For a hooked game that only adds duplicate or misread lines.",
            "Set this game's OCR to on demand (Start Manual OCR) and use the OCR hotkey for pictures or text "
            "the hook misses.",
        )
    elif readers:
        detail = f"Text comes from {', '.join(readers)}."
        if ocr:
            detail += " OCR is ready on demand (hotkey) for pictures or text the hook misses."
        source_check = Check("text_source", title, STATUS_OK, detail)
    else:
        mode_text = "on demand (hotkey)" if ocr_mode == "manual" else "scanning the screen"
        source_check = Check("text_source", title, STATUS_OK, f"Text comes from GSM OCR, {mode_text}.")
    return [source_check, check_recent_line(status)]


def _inhouse_sources() -> tuple[dict, dict]:
    """GSM's own text sources (built-in hook, OCR) and how they run."""
    try:
        from GameSentenceMiner.gametext import inhouse_source_modes, inhouse_sources_active

        return dict(inhouse_sources_active), dict(inhouse_source_modes)
    except Exception:  # noqa: BLE001 - the page must render even if text intake is not up
        return {}, {}


def check_recent_line(status: dict, now: datetime | None = None) -> Check:
    title = "Text received recently"
    fix = "Advance the game's text; lines should appear on the texthooker page."
    raw = status.get("last_line_received")
    if not raw:
        return Check("recent_line", title, STATUS_WARN, "No line received since GSM started.", fix)
    try:
        received = datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return Check("recent_line", title, STATUS_WARN, f"Last line at {raw} (unrecognised time format).", fix)
    age = max(0, int(((now or datetime.now()) - received).total_seconds()))
    detail = f"Last line {_format_age(age)} ago ({raw})."
    if age <= RECENT_LINE_SECONDS:
        return Check("recent_line", title, STATUS_OK, detail)
    return Check("recent_line", title, STATUS_WARN, detail + " Fine if you are not reading right now.", fix)


def _format_age(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 90 * 60:
        return f"{seconds // 60} min"
    if seconds < 48 * 3600:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} days"


def check_browser_connect(last: dict | None, now: float | None = None) -> Check:
    """GSM Connect: subtitles and manga text from the browser, filed under their own titles."""
    title = "Browser (GSM Connect)"
    if not last:
        return Check(
            "browser_connect",
            title,
            STATUS_SKIP,
            "No browser lines since GSM started. Only needed for YouTube, anime or manga in the browser.",
            "Load the gsm_connect folder as a browser extension (see gsm_connect/README.md).",
        )
    age = max(0, int((now or time.time()) - float(last.get("at") or 0)))
    return Check(
        "browser_connect",
        title,
        STATUS_OK,
        f"Last line {_format_age(age)} ago from {last.get('site') or 'the browser'}: {last.get('title') or 'untitled'}.",
    )


def check_texthooker(config) -> Check:
    general = config.general
    main_url = f"http://localhost:{general.single_port}/texthooker"
    legacy_url = f"http://localhost:{general.texthooker_port}"
    detail = f"This page is served by GSM. Open the texthooker in Firefox at {legacy_url} (redirects to {main_url})."
    return Check("texthooker", "Texthooker reachable", STATUS_OK, detail)


# ---------------------------------------------------------------------------
# Anki checks
# ---------------------------------------------------------------------------


def configured_anki_fields(config) -> dict[str, str]:
    """GSM field label → Anki field name for every field GSM is configured to write."""
    anki_cfg = config.anki
    fields: dict[str, str] = {}
    for key, label in ANKI_FIELD_LABELS.items():
        field_cfg = getattr(anki_cfg, key, None)
        name = str(getattr(field_cfg, "name", "") or "").strip()
        if not name or not getattr(field_cfg, "enabled", True):
            continue
        # Media fields only matter when that media is captured at all.
        if key == "sentence_audio" and not getattr(config.audio, "enabled", True):
            continue
        if key in ("picture", "previous_image") and not getattr(config.screenshot, "enabled", True):
            continue
        fields[label] = name
    if getattr(config.ai, "add_to_anki", False) and str(config.ai.anki_field or "").strip():
        fields["AI translation"] = config.ai.anki_field.strip()
    return fields


def check_anki(config, anki_call: Callable | None = None) -> list[Check]:
    call = anki_call or _anki_call
    anki_cfg = config.anki
    titles = {
        "ankiconnect": "AnkiConnect",
        "anki_deck": "Anki decks",
        "anki_note_type": "Note type and fields",
        "anki_fields_stale": "GSM field list up to date",
        "anki_recent_notes": "Yomitan → Anki: recent notes",
    }

    def skipped(reason: str) -> list[Check]:
        return [Check(cid, title, STATUS_SKIP, reason) for cid, title in titles.items() if cid != "ankiconnect"]

    if not anki_cfg.enabled:
        return [
            Check(
                "ankiconnect",
                titles["ankiconnect"],
                STATUS_WARN,
                "Anki integration is turned off in GSM.",
                "GSM Settings → Anki: enable Anki.",
            )
        ] + skipped("Anki integration is off.")

    try:
        version = call("version", timeout=1.0)
    except AnkiCallError as exc:
        return [
            Check("ankiconnect", titles["ankiconnect"], STATUS_FAIL, f"{anki_cfg.url}: {exc}", ANKI_CONNECT_FIX)
        ] + skipped("AnkiConnect is not reachable.")
    checks = [Check("ankiconnect", titles["ankiconnect"], STATUS_OK, f"{anki_cfg.url} answers (API v{version}).")]

    try:
        decks = sorted(call("deckNames") or [])
        checks.append(
            Check(
                "anki_deck",
                titles["anki_deck"],
                STATUS_OK if decks else STATUS_WARN,
                f"{len(decks)} decks: {', '.join(decks)}" if decks else "No decks found.",
                "" if decks else "Create the mining deck that Yomitan's Anki card format points to.",
            )
        )
    except AnkiCallError as exc:
        checks.append(Check("anki_deck", titles["anki_deck"], STATUS_FAIL, f"deckNames failed: {exc}"))

    note_type = str(anki_cfg.note_type or "").strip()
    if not note_type:
        fix = "GSM Settings → Anki: choose your note type (Lapis) and press Refresh Fields."
        checks.append(Check("anki_note_type", titles["anki_note_type"], STATUS_WARN, "No note type set in GSM.", fix))
        checks.append(Check("anki_fields_stale", titles["anki_fields_stale"], STATUS_SKIP, "No note type set."))
        checks.append(Check("anki_recent_notes", titles["anki_recent_notes"], STATUS_SKIP, "No note type set."))
        return checks

    try:
        models = call("modelNames") or []
        live_fields = call("modelFieldNames", modelName=note_type) if note_type in models else None
    except AnkiCallError as exc:
        checks.append(Check("anki_note_type", titles["anki_note_type"], STATUS_FAIL, f"AnkiConnect error: {exc}"))
        live_fields = None
        models = None

    if models is not None and live_fields is None:
        checks.append(
            Check(
                "anki_note_type",
                titles["anki_note_type"],
                STATUS_FAIL,
                f"Note type '{note_type}' does not exist in Anki. Found: {', '.join(sorted(models)) or 'none'}.",
                "GSM Settings → Anki: pick the note type your Yomitan cards use, then press Refresh Fields.",
            )
        )
    if live_fields is None:
        checks.append(Check("anki_fields_stale", titles["anki_fields_stale"], STATUS_SKIP, "Note type unavailable."))
    else:
        live = list(live_fields)
        wanted = configured_anki_fields(config)
        missing = [(label, name) for label, name in wanted.items() if name not in live]
        if missing:
            names = ", ".join(f"{name} ({label})" for label, name in missing)
            checks.append(
                Check(
                    "anki_note_type",
                    titles["anki_note_type"],
                    STATUS_FAIL,
                    f"'{note_type}' is missing fields GSM writes to: {names}.",
                    " ".join(
                        f"In Anki: Tools → Manage Note Types → {note_type} → Fields → Add '{name}'."
                        for _, name in missing
                    )
                    + " Warning: adding a field forces a one-way AnkiWeb sync."
                    + " Or change the mapping in GSM Settings → Anki.",
                )
            )
        else:
            checks.append(
                Check(
                    "anki_note_type",
                    titles["anki_note_type"],
                    STATUS_OK,
                    f"'{note_type}' has every field GSM writes to: "
                    + ", ".join(f"{name} ({label})" for label, name in wanted.items())
                    + ".",
                )
            )
        stored = list(anki_cfg.available_fields or [])
        only_live = [f for f in live if f not in stored]
        only_stored = [f for f in stored if f not in live]
        if only_live or only_stored:
            parts = []
            if only_live:
                parts.append(f"in Anki but not in GSM's list: {', '.join(only_live)}")
            if only_stored:
                parts.append(f"in GSM's list but not in Anki: {', '.join(only_stored)}")
            checks.append(
                Check(
                    "anki_fields_stale",
                    titles["anki_fields_stale"],
                    STATUS_WARN,
                    "GSM's saved field list is out of date (" + "; ".join(parts) + ").",
                    "Open GSM Settings → Anki and press Refresh Fields.",
                )
            )
        else:
            checks.append(
                Check("anki_fields_stale", titles["anki_fields_stale"], STATUS_OK, "Matches the note type in Anki.")
            )

    query = f'"note:{note_type}" added:{RECENT_NOTES_DAYS}'
    try:
        note_ids = call("findNotes", timeout=4.0, query=query) or []
        count = len(note_ids)
        checks.append(
            Check(
                "anki_recent_notes",
                titles["anki_recent_notes"],
                STATUS_OK if count else STATUS_WARN,
                f"{count} '{note_type}' notes added in the last {RECENT_NOTES_DAYS} days.",
                ""
                if count
                else f"Mine one word from the texthooker in Firefox; a {note_type} note should appear in Anki.",
            )
        )
    except AnkiCallError as exc:
        checks.append(Check("anki_recent_notes", titles["anki_recent_notes"], STATUS_FAIL, f"findNotes failed: {exc}"))
    return checks


# ---------------------------------------------------------------------------
# AI checks
# ---------------------------------------------------------------------------

_ai_test_lock = threading.Lock()
_ai_test_cache: dict[str, object] = {"at": 0.0, "key": None, "check": None}


def _ai_model(ai_cfg) -> str:
    from GameSentenceMiner.ai.service import AIService

    return AIService._get_model_for_provider(ai_cfg) or ""


def _ai_url(ai_cfg) -> str:
    return {
        "OpenAI": getattr(ai_cfg, "open_ai_url", ""),
        "Ollama": getattr(ai_cfg, "ollama_url", ""),
        "LM Studio": getattr(ai_cfg, "lm_studio_url", ""),
    }.get(ai_cfg.provider, "")


def check_ai_configured(config) -> Check:
    ai_cfg = config.ai
    if ai_cfg.is_configured():
        url = _ai_url(ai_cfg)
        detail = f"Provider {ai_cfg.provider}, model {_ai_model(ai_cfg)}" + (f", URL {url}" if url else "") + "."
        return Check("ai_configured", "AI configured", STATUS_OK, detail)
    status = STATUS_FAIL if ai_cfg.add_to_anki else STATUS_WARN
    return Check(
        "ai_configured",
        "AI configured",
        status,
        f"Provider '{ai_cfg.provider or 'none'}' is missing a model, URL or API key.",
        AI_SETUP_FIX,
    )


def describe_ai_error(exc: BaseException, ai_cfg) -> str:
    """Short, credential-free explanation of a failed test call."""
    from GameSentenceMiner.ai.setup import ai_error_message

    text = str(exc).lower()
    model = _ai_model(ai_cfg)
    url = _ai_url(ai_cfg)
    if any(t in text for t in ("401", "403", "unauthorized", "invalid api key", "incorrect api key")):
        return "401/403: the provider rejected the API key. Paste a valid key in GSM Settings → AI."
    if "404" in text or "not found" in text or "does not exist" in text:
        return f"404: model '{model}' was not found at the provider. Check the model name in GSM Settings → AI."
    if any(t in text for t in ("timed out", "timeout", "connection", "connect", "name resolution", "getaddrinfo")):
        return f"Could not reach {url or 'the provider'} (timeout or network error). Check the URL and your connection."
    if "429" in text or "rate limit" in text or "quota" in text:
        return "429: rate limit or quota reached. Wait and retry, or check your provider account."
    return ai_error_message(exc)


def _default_ai_tester(config):
    """One tiny request through the configured provider. Returns (model, latency_ms, text)."""
    from GameSentenceMiner.ai.service import AIService, snapshot_config

    service = AIService(snapshot_config(config.ai, config.general), logger)
    prompt = "Hello" if config.ai.provider == "DeepL" else "Reply with only OK."
    started = time.perf_counter()
    response = service._execute_request(replace(service._make_request(prompt, "health"), max_tokens=AI_TEST_MAX_TOKENS))
    latency = getattr(response, "latency_ms", None) or int((time.perf_counter() - started) * 1000)
    return response.model, int(latency), response.text or ""


def check_ai_reachable(config, run_test: bool, tester: Callable | None = None, now: Callable = time.monotonic) -> Check:
    title = "AI reachable"
    ai_cfg = config.ai
    if not ai_cfg.is_configured():
        return Check("ai_reachable", title, STATUS_SKIP, "AI is not configured.")
    if not run_test:
        return Check(
            "ai_reachable",
            title,
            STATUS_SKIP,
            "Not tested on page load. Press Re-check to send one tiny test request (costs a few tokens).",
        )
    cache_key = (ai_cfg.provider, _ai_model(ai_cfg), _ai_url(ai_cfg))
    with _ai_test_lock:
        cached = _ai_test_cache.get("check")
        if (
            cached is not None
            and _ai_test_cache.get("key") == cache_key
            and now() - float(_ai_test_cache.get("at") or 0) < AI_TEST_COOLDOWN_SECONDS
        ):
            result = Check(**asdict(cached))
            result.detail += f" (result from the last {AI_TEST_COOLDOWN_SECONDS} s; not re-sent)"
            return result
        result = _run_ai_test(config, tester or _default_ai_tester)
        _ai_test_cache.update({"at": now(), "key": cache_key, "check": result})
        return result


def _run_ai_test(config, tester: Callable) -> Check:
    title = "AI reachable"
    ai_cfg = config.ai
    primary = _ai_model(ai_cfg)
    try:
        model, latency_ms, text = tester(config)
        if not text or str(text).startswith("Processing failed:"):
            raise ValueError(text or "empty reply")
    except Exception as exc:  # noqa: BLE001 - SDK error types vary; never echo their payloads.
        logger.info(f"Setup check AI test failed: {type(exc).__name__}")
        return Check("ai_reachable", title, STATUS_FAIL, describe_ai_error(exc, ai_cfg), AI_SETUP_FIX)
    detail = f"{ai_cfg.provider} / {model} answered in {latency_ms} ms."
    if primary and model and model != primary:
        return Check(
            "ai_reachable",
            title,
            STATUS_WARN,
            detail + f" The primary model '{primary}' failed and the backup answered.",
            f"Check that '{primary}' is still available at your provider, or make it the backup.",
        )
    return Check("ai_reachable", title, STATUS_OK, detail)


# ---------------------------------------------------------------------------
# OBS
# ---------------------------------------------------------------------------


def check_obs(status: dict) -> Check:
    if status.get("obs_connected"):
        return Check("obs", "OBS", STATUS_OK, "Connected. Audio and screenshots can be captured.")
    return Check(
        "obs",
        "OBS",
        STATUS_WARN,
        "Not connected. Reading and lookups work; cards get no sentence audio or picture.",
        "GSM Settings → OBS: start OBS or enable GSM's bundled OBS.",
    )


# ---------------------------------------------------------------------------
# Runner + routes
# ---------------------------------------------------------------------------


def summarize(checks: list[Check]) -> dict:
    counts = {s: 0 for s in (STATUS_OK, STATUS_WARN, STATUS_FAIL, STATUS_SKIP)}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    parts = [f"{counts[s]} {s}" for s in (STATUS_OK, STATUS_WARN, STATUS_FAIL, STATUS_SKIP) if counts[s]]
    return {"counts": counts, "text": ", ".join(parts)}


def run_checks(
    run_ai_test: bool = False,
    config=None,
    status: dict | None = None,
    anki_call: Callable | None = None,
    ai_tester: Callable | None = None,
    extra_checks: list[Callable[[], list[Check]]] | None = None,
    inhouse: tuple[dict, dict] | None = None,
    connect_last: dict | None = None,
) -> dict:
    config = config or get_config()
    status = status if status is not None else gsm_status.to_dict()
    checks: list[Check] = []
    checks.extend(check_text_sources(config, status, inhouse))
    checks.append(check_texthooker(config))
    if connect_last is None:
        from GameSentenceMiner.web.connect_api import last_activity

        connect_last = last_activity()
    checks.append(check_browser_connect(connect_last))
    checks.extend(check_anki(config, anki_call))
    checks.append(check_ai_configured(config))
    checks.append(check_ai_reachable(config, run_ai_test, ai_tester))
    checks.append(check_obs(status))
    for extra in extra_checks or []:
        try:
            checks.extend(extra())
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the rest
            logger.debug("Setup check failed to run", exc_info=True)
            checks.append(Check(getattr(extra, "__name__", "extra"), "Extra check", STATUS_FAIL, str(exc)))
    return {
        "checks": [asdict(c) for c in checks],
        "summary": summarize(checks),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "ai_tested": bool(run_ai_test),
    }


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def register_setup_check_routes(app):
    @app.route("/setup-check")
    def setup_check_page():
        return render_template("setup_check.html", config=get_config())

    @app.route("/api/setup-check", methods=["GET"])
    def setup_check_api():
        from GameSentenceMiner.util import yomitan_sync

        result = run_checks(
            run_ai_test=_truthy(request.args.get("ai_test")),
            extra_checks=[yomitan_sync.setup_checks],
        )
        return jsonify(result), 200
