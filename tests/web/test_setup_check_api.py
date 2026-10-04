from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from GameSentenceMiner.util.config.configuration import Ai, Anki, Audio, General, Screenshot
from GameSentenceMiner.web import setup_check_api, texthooking_page
from GameSentenceMiner.web.setup_check_api import AnkiCallError

LAPIS_FIELDS = [
    "Expression",
    "ExpressionReading",
    "Sentence",
    "SentenceFurigana",
    "SentenceAudio",
    "Picture",
    "MiscInfo",
    "SentenceTranslation",
]


def _config(**ai_overrides):
    anki = Anki(note_type="Lapis", available_fields=list(LAPIS_FIELDS))
    ai = Ai(add_to_anki=True, anki_field="SentenceTranslation", **ai_overrides)
    return SimpleNamespace(general=General(), anki=anki, ai=ai, audio=Audio(), screenshot=Screenshot())


def _configured_ai():
    return _config(provider="OpenAI", open_ai_api_key="k", open_ai_model="m-pro", open_ai_url="https://nano/api/v1")


def _fake_anki(fields=None, notes=(1, 2), decks=("General Mining",), models=("Lapis",), fail=None):
    calls = []

    def call(action, timeout=None, **params):
        calls.append((action, params))
        if fail and action in fail:
            raise AnkiCallError(fail[action])
        return {
            "version": 6,
            "deckNames": list(decks),
            "modelNames": list(models),
            "modelFieldNames": list(LAPIS_FIELDS if fields is None else fields),
            "findNotes": list(notes),
        }[action]

    call.calls = calls
    return call


def _by_id(result):
    return {c["id"]: c for c in result["checks"]}


@pytest.fixture(autouse=True)
def _reset_ai_cache():
    setup_check_api._ai_test_cache.update({"at": 0.0, "key": None, "check": None})
    yield


def _status(**overrides):
    status = {
        "websockets_connected": {"ws://localhost:2333/api/ws/text/origin": "LunaTranslator"},
        "last_line_received": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "obs_connected": True,
    }
    status.update(overrides)
    return status


def test_all_green_without_ai_test():
    tester_calls = []
    result = setup_check_api.run_checks(
        config=_configured_ai(),
        status=_status(),
        anki_call=_fake_anki(),
        ai_tester=lambda cfg: tester_calls.append(cfg),
    )
    checks = _by_id(result)
    assert checks["text_source_luna"]["status"] == "ok"
    assert checks["recent_line"]["status"] == "ok"
    assert checks["ankiconnect"]["status"] == "ok"
    assert checks["anki_note_type"]["status"] == "ok"
    assert checks["anki_fields_stale"]["status"] == "ok"
    assert checks["anki_recent_notes"]["status"] == "ok"
    assert checks["ai_configured"]["status"] == "ok"
    assert checks["obs"]["status"] == "ok"
    # Page load must never spend tokens.
    assert checks["ai_reachable"]["status"] == "skip"
    assert tester_calls == []
    assert result["ai_tested"] is False
    assert result["summary"]["counts"]["fail"] == 0


def test_luna_not_connected_fails_with_fix():
    checks = _by_id(
        setup_check_api.run_checks(
            config=_configured_ai(),
            status=_status(websockets_connected={}),
            anki_call=_fake_anki(),
        )
    )
    luna = checks["text_source_luna"]
    assert luna["status"] == "fail"
    assert "2333" in luna["fix"] and "network_websocket" in luna["fix"]
    assert "LunaTranslator (localhost:2333): not connected" in luna["detail"]


def test_luna_source_missing_from_config():
    config = _configured_ai()
    config.general.websocket_sources = [s for s in config.general.websocket_sources if "2333" not in s.uri]
    checks = _by_id(setup_check_api.run_checks(config=config, status=_status(), anki_call=_fake_anki()))
    assert checks["text_source_luna"]["status"] == "fail"
    assert "No enabled source on port 2333" in checks["text_source_luna"]["detail"]


def test_plain_ws_key_counts_as_connected():
    status = _status(websockets_connected={"ws://localhost:2333": "LunaTranslator"})
    checks = _by_id(setup_check_api.run_checks(config=_configured_ai(), status=status, anki_call=_fake_anki()))
    assert checks["text_source_luna"]["status"] == "ok"


def test_stale_last_line_warns():
    old = datetime(2026, 1, 1, 12, 0, 0)
    check = setup_check_api.check_recent_line(
        {"last_line_received": old.strftime("%Y-%m-%d %H:%M:%S")}, now=old + timedelta(hours=3)
    )
    assert check.status == "warn" and "3 h ago" in check.detail
    assert setup_check_api.check_recent_line({}).status == "warn"


def test_anki_down_fails_and_skips_dependents():
    checks = _by_id(
        setup_check_api.run_checks(
            config=_configured_ai(),
            status=_status(),
            anki_call=_fake_anki(fail={"version": "connection refused (is Anki running?)"}),
        )
    )
    assert checks["ankiconnect"]["status"] == "fail"
    assert "2055492159" in checks["ankiconnect"]["fix"]
    for cid in ("anki_deck", "anki_note_type", "anki_fields_stale", "anki_recent_notes"):
        assert checks[cid]["status"] == "skip"


def test_missing_note_field_names_each_field():
    fields = [f for f in LAPIS_FIELDS if f not in ("SentenceTranslation", "Picture")]
    checks = _by_id(
        setup_check_api.run_checks(config=_configured_ai(), status=_status(), anki_call=_fake_anki(fields=fields))
    )
    note = checks["anki_note_type"]
    assert note["status"] == "fail"
    assert "SentenceTranslation (AI translation)" in note["detail"]
    assert "Picture (Picture)" in note["detail"]
    assert "Fields → Add 'SentenceTranslation'" in note["fix"]
    assert "one-way AnkiWeb sync" in note["fix"]


def test_disabled_media_fields_are_not_required():
    config = _configured_ai()
    config.screenshot.enabled = False
    fields = [f for f in LAPIS_FIELDS if f != "Picture"]
    checks = _by_id(setup_check_api.run_checks(config=config, status=_status(), anki_call=_fake_anki(fields=fields)))
    assert checks["anki_note_type"]["status"] == "ok"


def test_stale_gsm_field_list_warns():
    # The owner's snapshot: GSM's saved list predates the SentenceTranslation field.
    config = _configured_ai()
    config.anki.available_fields = [f for f in LAPIS_FIELDS if f != "SentenceTranslation"]
    checks = _by_id(setup_check_api.run_checks(config=config, status=_status(), anki_call=_fake_anki()))
    stale = checks["anki_fields_stale"]
    assert stale["status"] == "warn"
    assert "SentenceTranslation" in stale["detail"]
    assert "Refresh Fields" in stale["fix"]


def test_unknown_note_type_fails():
    checks = _by_id(
        setup_check_api.run_checks(
            config=_configured_ai(), status=_status(), anki_call=_fake_anki(models=("Basic", "JP Mining Note"))
        )
    )
    assert checks["anki_note_type"]["status"] == "fail"
    assert "does not exist" in checks["anki_note_type"]["detail"]
    assert checks["anki_fields_stale"]["status"] == "skip"


def test_no_recent_notes_warns_and_queries_note_type():
    fake = _fake_anki(notes=())
    checks = _by_id(setup_check_api.run_checks(config=_configured_ai(), status=_status(), anki_call=fake))
    assert checks["anki_recent_notes"]["status"] == "warn"
    assert ("findNotes", {"query": '"note:Lapis" added:7'}) in fake.calls


def test_anki_calls_are_read_only():
    fake = _fake_anki()
    setup_check_api.run_checks(config=_configured_ai(), status=_status(), anki_call=fake)
    assert {a for a, _ in fake.calls} <= {"version", "deckNames", "modelNames", "modelFieldNames", "findNotes"}


def test_ai_not_configured_fails_when_cards_need_it():
    checks = _by_id(setup_check_api.run_checks(config=_config(), status=_status(), anki_call=_fake_anki()))
    assert checks["ai_configured"]["status"] == "fail"
    assert "nano-gpt.com" in checks["ai_configured"]["fix"]
    assert checks["ai_reachable"]["status"] == "skip"


def test_ai_test_runs_only_on_request_and_reports_latency():
    calls = []

    def tester(cfg):
        calls.append(cfg)
        return "m-pro", 420, "OK"

    checks = _by_id(
        setup_check_api.run_checks(
            run_ai_test=True, config=_configured_ai(), status=_status(), anki_call=_fake_anki(), ai_tester=tester
        )
    )
    assert len(calls) == 1
    assert checks["ai_reachable"]["status"] == "ok"
    assert "m-pro answered in 420 ms" in checks["ai_reachable"]["detail"]


def test_ai_test_cooldown_does_not_resend():
    calls = []

    def tester(cfg):
        calls.append(cfg)
        return "m-pro", 10, "OK"

    config = _configured_ai()
    first = setup_check_api.check_ai_reachable(config, True, tester, now=lambda: 100.0)
    second = setup_check_api.check_ai_reachable(config, True, tester, now=lambda: 105.0)
    third = setup_check_api.check_ai_reachable(config, True, tester, now=lambda: 200.0)
    assert len(calls) == 2
    assert first.status == second.status == third.status == "ok"
    assert "not re-sent" in second.detail


@pytest.mark.parametrize(
    "error, expected",
    [
        (Exception("Error code: 401 - invalid api key"), "401/403"),
        (Exception("Error code: 404 - model not found"), "model 'm-pro' was not found"),
        (Exception("Request timed out."), "Could not reach https://nano/api/v1"),
        (Exception("Error code: 429 rate limit"), "429"),
    ],
)
def test_ai_test_failure_messages(error, expected):
    def tester(cfg):
        raise error

    check = setup_check_api.check_ai_reachable(_configured_ai(), True, tester)
    assert check.status == "fail"
    assert expected in check.detail
    assert "invalid api key" not in check.detail.lower() or "401/403" in check.detail


def test_ai_backup_model_answer_warns():
    check = setup_check_api.check_ai_reachable(_configured_ai(), True, lambda cfg: ("m-flash", 50, "OK"))
    assert check.status == "warn"
    assert "primary model 'm-pro' failed" in check.detail


def test_processing_failed_text_is_a_failure():
    check = setup_check_api.check_ai_reachable(
        _configured_ai(), True, lambda cfg: ("m-pro", 5, "Processing failed: 401 unauthorized")
    )
    assert check.status == "fail" and "401/403" in check.detail


def test_obs_down_is_warning_not_failure():
    checks = _by_id(
        setup_check_api.run_checks(config=_configured_ai(), status=_status(obs_connected=False), anki_call=_fake_anki())
    )
    assert checks["obs"]["status"] == "warn"


def test_summary_text():
    summary = setup_check_api.summarize(
        [
            setup_check_api.Check("a", "A", "ok"),
            setup_check_api.Check("b", "B", "ok"),
            setup_check_api.Check("c", "C", "fail"),
        ]
    )
    assert summary["text"] == "2 ok, 1 fail"


def test_broken_extra_check_is_reported_not_raised():
    def broken():
        raise RuntimeError("boom")

    result = setup_check_api.run_checks(
        config=_configured_ai(), status=_status(), anki_call=_fake_anki(), extra_checks=[broken]
    )
    assert _by_id(result)["broken"]["status"] == "fail"


@pytest.fixture
def client():
    # Own app: the shared texthooker app refuses new routes once another test has used it.
    app = Flask(__name__, template_folder=str(Path(texthooking_page.__file__).parent / "templates"))
    setup_check_api.register_setup_check_routes(app)
    app.config["TESTING"] = True
    return app.test_client()


def test_routes(client, monkeypatch):
    seen = []

    def fake_run(run_ai_test=False):
        seen.append(run_ai_test)
        return {"checks": [], "summary": {"counts": {}, "text": ""}, "checked_at": "x", "ai_tested": run_ai_test}

    monkeypatch.setattr(setup_check_api, "run_checks", fake_run)
    assert client.get("/api/setup-check").status_code == 200
    assert client.get("/api/setup-check?ai_test=1").json["ai_tested"] is True
    assert seen == [False, True]
    page = client.get("/setup-check")
    assert page.status_code == 200
    assert b"setup_check.js" in page.data
