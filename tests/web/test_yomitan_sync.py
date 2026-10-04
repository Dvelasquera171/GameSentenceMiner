from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from GameSentenceMiner.util import yomitan_sync
from GameSentenceMiner.util.yomitan_sync import YomitanSyncError
from GameSentenceMiner.web import yomitan_sync_api

LAPIS = {
    "name": "Expression",
    "icon": "big-circle",
    "type": "term",
    "deck": "General Mining",
    "model": "Lapis",
    "fields": {
        "Expression": {"value": "{expression}", "overwriteMode": "coalesce"},
        "Sentence": {"value": "{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}", "overwriteMode": "coalesce"},
    },
}


def _options(card_formats=None, dictionaries=("Jitendex", "JPDBv2")):
    return {
        "version": 77,
        "profileCurrent": 0,
        "profiles": [
            {
                "name": "Default",
                "conditionGroups": [],
                "options": {
                    "general": {"language": "ja"},
                    "dictionaries": [{"name": n, "enabled": True} for n in dictionaries],
                    "anki": {
                        "enable": True,
                        "server": "http://127.0.0.1:8765",
                        "cardFormats": copy.deepcopy(card_formats if card_formats is not None else [LAPIS]),
                    },
                },
            }
        ],
    }


@pytest.fixture
def sync_dir(tmp_path, monkeypatch):
    folder = tmp_path / "yomitan_sync"
    monkeypatch.setattr(yomitan_sync, "sync_dir", lambda: folder)
    yomitan_sync._settings_cache.update({"key": None, "value": None})
    yomitan_sync._pending.clear()
    yomitan_sync._seen_results.clear()
    yomitan_sync._state.update(
        {
            "status": None,
            "status_at": 0.0,
            "status_error": "",
            "progress": None,
            "results": {},
            "dictionary_job": {"running": False, "request_id": "", "started_at": 0.0},
        }
    )
    yomitan_sync._watch.update({"connected": False, "status_failed": False, "attempted": set()})
    return folder


def _write_settings(
    folder: Path, name="yomitan-settings-2026-10-03-10-00-00.json", options=None, wrap=True, mtime=None
):
    folder.mkdir(parents=True, exist_ok=True)
    options = options or _options()
    data = {"version": 0, "date": "2026-10-03 10:00:00", "options": options} if wrap else options
    path = folder / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _write_dictionaries(folder: Path, name="yomitan-dictionaries-2026-10-03-10-00-00.json"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text('{"formatName":"dexie","formatVersion":1,"data":{}}', encoding="utf-8")
    return path


_DELIVERIES: list = []


@pytest.fixture(autouse=True)
def _join_deliveries():
    yield
    # A late reply must not leak into the next test's state.
    while _DELIVERIES:
        _DELIVERIES.pop().join(timeout=2)


class FakeOverlay:
    """Stands in for the overlay websocket: answers each request like GSM_Overlay/yomitan_sync.js."""

    def __init__(self, monkeypatch, report=None, fail=None, answer=True):
        self.sent = []
        self.report = report or {}
        self.fail = fail
        self.answer = answer
        self.last_sync = {}
        monkeypatch.setattr(yomitan_sync, "_overlay_connected", lambda: True)
        monkeypatch.setattr(yomitan_sync, "_send_to_overlay", self.send)

    def send(self, message):
        self.sent.append(message)
        if not self.answer or message["type"] == "yomitan-sync-dictionaries":
            return
        kind = {"yomitan-sync-settings": "settings", "yomitan-sync-status-request": "status"}[message["type"]]
        if kind == "settings" and not self.fail:
            self.last_sync["settings"] = {
                "hash": message["data"]["settings_hash"],
                "exportDate": message["data"]["export_date"],
            }
        reply = {"type": "yomitan-sync-result", "request_id": message["request_id"], "kind": kind}
        if self.fail:
            reply.update(success=False, error=self.fail)
        else:
            reply.update(success=True, lastSync=copy.deepcopy(self.last_sync), **copy.deepcopy(self.report))

        # Like the real overlay: answers arrive on another thread, once per connection.
        def deliver():
            time.sleep(0.01)
            yomitan_sync.accept_overlay_message(reply)
            yomitan_sync.accept_overlay_message(dict(reply))

        thread = threading.Thread(target=deliver, daemon=True)
        _DELIVERIES.append(thread)
        thread.start()


def _report(card_formats=None, installed=("Jitendex", "JPDBv2")):
    return {
        "profileName": "GSM - Lapis",
        "ankiEnabled": True,
        "cardFormats": yomitan_sync.normalize_card_formats({"cardFormats": card_formats or [LAPIS]}),
        "installed": list(installed),
    }


# --- export discovery ------------------------------------------------------


def test_extract_export_options_accepts_both_shapes():
    options = _options()
    assert yomitan_sync.extract_export_options({"version": 0, "options": options}) is options
    assert yomitan_sync.extract_export_options(options) is options
    with pytest.raises(YomitanSyncError, match="not a Yomitan settings export"):
        yomitan_sync.extract_export_options({"version": 0})


def test_settings_export_uses_newest_default_named_file(sync_dir):
    assert yomitan_sync.settings_export() is None
    _write_settings(sync_dir, "yomitan-settings-2026-09-01-00-00-00.json", mtime=time.time() - 100)
    newest = _write_settings(sync_dir, "settings.json", options=_options(dictionaries=("Kanjium",)), wrap=False)
    export = yomitan_sync.settings_export()
    assert export["name"] == newest.name
    assert export["options"]["profiles"][0]["options"]["dictionaries"][0]["name"] == "Kanjium"
    assert len(export["hash"]) == 64 and export["date"]


def test_settings_export_reports_invalid_json(sync_dir):
    sync_dir.mkdir()
    (sync_dir / "settings.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(YomitanSyncError, match="not valid JSON"):
        yomitan_sync.settings_export()


def test_dictionaries_export_fingerprint_changes_with_file(sync_dir):
    path = _write_dictionaries(sync_dir)
    first = yomitan_sync.dictionaries_export()
    assert first["name"] == path.name and first["size"] == path.stat().st_size
    path.write_text('{"formatName":"dexie","formatVersion":1,"data":{"x":1}}', encoding="utf-8")
    assert yomitan_sync.dictionaries_export()["fingerprint"] != first["fingerprint"]


# --- card format comparison ---------------------------------------------------


def test_card_formats_compare_field_by_field():
    expected = yomitan_sync.normalize_card_formats({"cardFormats": [LAPIS]})
    same = yomitan_sync.normalize_card_formats({"cardFormats": [{**copy.deepcopy(LAPIS), "icon": "small-circle"}]})
    assert yomitan_sync.compare_card_formats(expected, same) == []

    changed = copy.deepcopy(LAPIS)
    changed["deck"] = "Other"
    changed["fields"]["Sentence"]["value"] = "{sentence}"
    changed["fields"]["Expression"]["overwriteMode"] = "overwrite"
    changed["fields"]["Extra"] = {"value": "", "overwriteMode": "coalesce"}
    diffs = yomitan_sync.compare_card_formats(expected, yomitan_sync.normalize_card_formats({"cardFormats": [changed]}))
    text = "\n".join(diffs)
    assert 'deck: Firefox "General Mining", overlay "Other"' in text
    assert "field Sentence value" in text
    assert "field Expression overwriteMode" in text
    assert "field Extra: only in the overlay" in text
    assert yomitan_sync.compare_card_formats(expected, [])[0].startswith("card format count")


# --- overlay messaging --------------------------------------------------------


def test_sync_settings_sends_export_and_waits_for_overlay(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    overlay = FakeOverlay(monkeypatch, report=_report())
    result = yomitan_sync.sync_settings(timeout=5)
    message = overlay.sent[0]
    assert message["type"] == "yomitan-sync-settings"
    assert message["data"]["settings"]["profiles"][0]["name"] == "Default"
    assert message["data"]["export_date"] == "2026-10-03 10:00:00"
    assert message["deadline"] > time.time() * 1000
    assert result["success"] and result["profileName"] == "GSM - Lapis"
    time.sleep(0.05)
    assert yomitan_sync.get_state()["status"]["profileName"] == "GSM - Lapis"


def test_sync_settings_surfaces_overlay_error(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    FakeOverlay(monkeypatch, fail="Yomitan did not keep the Firefox card formats")
    with pytest.raises(YomitanSyncError, match="did not keep"):
        yomitan_sync.sync_settings(timeout=5)


def test_sync_requires_overlay_and_export(sync_dir, monkeypatch):
    monkeypatch.setattr(yomitan_sync, "_overlay_connected", lambda: False)
    with pytest.raises(YomitanSyncError, match="No Firefox settings export"):
        yomitan_sync.sync_settings()
    _write_settings(sync_dir)
    with pytest.raises(YomitanSyncError, match="Start the GSM overlay"):
        yomitan_sync.sync_settings()


def test_sync_times_out_when_overlay_is_silent(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    FakeOverlay(monkeypatch, answer=False)
    with pytest.raises(YomitanSyncError, match="did not answer"):
        yomitan_sync.sync_settings(timeout=0.2)
    assert yomitan_sync._pending == {}


def test_dictionary_import_runs_once_then_resyncs_settings(sync_dir, monkeypatch):
    _write_dictionaries(sync_dir)
    overlay = FakeOverlay(monkeypatch)
    monkeypatch.setattr(yomitan_sync, "get_config", lambda: SimpleNamespace(general=SimpleNamespace(single_port=7275)))
    started = yomitan_sync.start_dictionary_import()
    assert started["started"] is True
    message = overlay.sent[0]
    assert message["data"]["url"] == "http://127.0.0.1:7275/api/yomitan-sync/dictionaries-file"
    assert message["data"]["fingerprint"] == yomitan_sync.dictionaries_export()["fingerprint"]
    with pytest.raises(YomitanSyncError, match="already running"):
        yomitan_sync.start_dictionary_import()

    yomitan_sync.accept_overlay_message({"type": "yomitan-sync-progress", "completedRows": 3, "totalRows": 9})
    assert yomitan_sync.get_state()["progress"]["completedRows"] == 3

    follow_ups = []
    monkeypatch.setattr(yomitan_sync, "_sync_settings_quietly", lambda: follow_ups.append(1))
    done = {"type": "yomitan-sync-result", "request_id": message["request_id"], "kind": "dictionaries", "success": True}
    yomitan_sync.accept_overlay_message(done)
    yomitan_sync.accept_overlay_message(dict(done))  # second connection
    time.sleep(0.05)
    assert follow_ups == [1]
    assert yomitan_sync.get_state()["dictionary_job"]["running"] is False


def test_unrelated_messages_are_not_consumed():
    assert yomitan_sync.accept_overlay_message({"type": "translate-request"}) is False


# --- watcher ------------------------------------------------------------------


def test_watcher_syncs_new_export_once_per_hash(sync_dir, monkeypatch):
    monkeypatch.setattr(yomitan_sync, "_overlay_connected", lambda: False)
    assert yomitan_sync.watch_once() is None

    _write_settings(sync_dir)
    overlay = FakeOverlay(monkeypatch, report=_report())
    assert yomitan_sync.watch_once() == "settings"
    assert [m["type"] for m in overlay.sent] == ["yomitan-sync-status-request", "yomitan-sync-settings"]
    time.sleep(0.05)
    # Synced: nothing more to do, even on later ticks.
    assert yomitan_sync.watch_once() is None
    assert len(overlay.sent) == 2

    _write_settings(sync_dir, options=_options(dictionaries=("Jitendex", "JPDBv2", "Kanjium")))
    time.sleep(0.05)
    assert yomitan_sync.watch_once() == "settings"


def test_watcher_does_not_retry_a_failing_export(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    overlay = FakeOverlay(monkeypatch, report=_report())
    overlay.fail = None
    status = yomitan_sync.request_status(timeout=5)
    assert status["success"]
    overlay.fail = "boom"
    yomitan_sync._watch["connected"] = True
    assert yomitan_sync.watch_once() == "settings"
    assert yomitan_sync.watch_once() is None


def test_watcher_imports_changed_dictionaries_before_settings(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    _write_dictionaries(sync_dir)
    overlay = FakeOverlay(monkeypatch, report=_report())
    monkeypatch.setattr(yomitan_sync, "get_config", lambda: SimpleNamespace(general=SimpleNamespace(single_port=7275)))
    assert yomitan_sync.watch_once() == "dictionaries"
    assert overlay.sent[-1]["type"] == "yomitan-sync-dictionaries"
    assert yomitan_sync.watch_once() is None  # import still running


# --- setup page rows ----------------------------------------------------------


def _rows():
    return {c.id: c for c in yomitan_sync.setup_checks()}


def test_rows_without_export(sync_dir):
    rows = _rows()
    assert rows["overlay_yomitan_sync"].status == "warn"
    assert "Export Settings" in rows["overlay_yomitan_sync"].fix
    assert str(sync_dir) in rows["overlay_yomitan_sync"].fix
    assert rows["overlay_yomitan_cards"].status == "skip"


def test_rows_when_overlay_not_running(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    monkeypatch.setattr(yomitan_sync, "_overlay_connected", lambda: False)
    rows = _rows()
    assert rows["overlay_yomitan_sync"].status == "skip"
    assert rows["overlay_yomitan_cards"].status == "skip"


def test_rows_report_stale_export_with_sync_button(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    FakeOverlay(monkeypatch, report=_report())
    rows = _rows()
    sync = rows["overlay_yomitan_sync"]
    assert sync.status == "warn"
    assert "newer than the overlay's last sync (never)" in sync.detail
    assert sync.action["url"] == "/api/yomitan-sync/sync"
    assert rows["overlay_yomitan_cards"].status == "ok"


def test_rows_ok_after_sync_and_fail_on_card_mismatch(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    overlay = FakeOverlay(monkeypatch, report=_report())
    yomitan_sync.sync_settings(timeout=5)
    time.sleep(0.05)
    rows = _rows()
    assert rows["overlay_yomitan_sync"].status == "ok", rows["overlay_yomitan_sync"].detail
    assert "GSM - Lapis" in rows["overlay_yomitan_sync"].detail
    assert rows["overlay_yomitan_cards"].status == "ok"
    assert "General Mining / Lapis (2 fields)" in rows["overlay_yomitan_cards"].detail

    other = copy.deepcopy(LAPIS)
    other["fields"]["Sentence"]["value"] = "{sentence}"
    overlay.report = _report(card_formats=[other])
    yomitan_sync._state["status_at"] = 0  # force a fresh status request
    rows = _rows()
    assert rows["overlay_yomitan_cards"].status == "fail"
    assert "field Sentence value" in rows["overlay_yomitan_cards"].detail


def test_rows_warn_about_missing_dictionaries(sync_dir, monkeypatch):
    _write_settings(sync_dir, options=_options(dictionaries=("Jitendex", "Kanjium")))
    FakeOverlay(monkeypatch, report=_report(installed=("Jitendex",)))
    yomitan_sync.sync_settings(timeout=5)
    time.sleep(0.05)
    sync = _rows()["overlay_yomitan_sync"]
    assert sync.status == "warn"
    assert "Kanjium" in sync.detail and "Export Dictionary Collection" in sync.fix


# --- routes -------------------------------------------------------------------


@pytest.fixture
def client():
    app = Flask(__name__)
    yomitan_sync_api.register_yomitan_sync_routes(app)
    app.config["TESTING"] = True
    return app.test_client()


def test_status_route(client, sync_dir, monkeypatch):
    _write_settings(sync_dir)
    monkeypatch.setattr(yomitan_sync, "_overlay_connected", lambda: False)
    data = client.get("/api/yomitan-sync/status").json
    assert data["settings_export"]["date"] == "2026-10-03 10:00:00"
    assert "options" not in data["settings_export"]
    assert data["overlay_connected"] is False
    assert client.get("/api/yomitan-sync/status", environ_overrides={"REMOTE_ADDR": "10.0.0.2"}).status_code == 403


def test_sync_route_errors(client, sync_dir, monkeypatch):
    monkeypatch.setattr(yomitan_sync, "_overlay_connected", lambda: False)
    assert client.post("/api/yomitan-sync/sync", json={"kind": "bogus"}).status_code == 400
    res = client.post("/api/yomitan-sync/sync", json={"kind": "settings"})
    assert res.status_code == 409 and "No Firefox settings export" in res.json["error"]
    cross = client.post("/api/yomitan-sync/sync", json={}, headers={"Origin": "https://evil.test"})
    assert cross.status_code == 403


def test_sync_route_settings(client, sync_dir, monkeypatch):
    _write_settings(sync_dir)
    FakeOverlay(monkeypatch, report=_report())
    res = client.post("/api/yomitan-sync/sync", json={"kind": "all"})
    assert res.status_code == 200
    assert res.json["settings"]["profileName"] == "GSM - Lapis"


def test_dictionaries_file_route(client, sync_dir):
    assert client.get("/api/yomitan-sync/dictionaries-file").status_code == 404
    _write_dictionaries(sync_dir)
    res = client.get("/api/yomitan-sync/dictionaries-file")
    assert res.status_code == 200 and b'"formatName":"dexie"' in res.data
    res.close()
    remote = client.get("/api/yomitan-sync/dictionaries-file", environ_overrides={"REMOTE_ADDR": "10.0.0.2"})
    assert remote.status_code == 403


def test_import_interrupted_by_overlay_restart_is_retried(sync_dir, monkeypatch):
    _write_settings(sync_dir)
    _write_dictionaries(sync_dir)
    overlay = FakeOverlay(
        monkeypatch, report={**_report(installed=()), "busy": {"settings": False, "dictionaries": False}}
    )
    monkeypatch.setattr(yomitan_sync, "get_config", lambda: SimpleNamespace(general=SimpleNamespace(single_port=7275)))
    assert yomitan_sync.watch_once() == "dictionaries"
    yomitan_sync._state["dictionary_job"]["started_at"] -= 10
    assert yomitan_sync.watch_once() is None  # still believed running

    # The overlay was closed and reopened: the new one answers "not importing".
    yomitan_sync._watch["connected"] = False
    assert yomitan_sync.watch_once() == "dictionaries"
    assert [m["type"] for m in overlay.sent].count("yomitan-sync-dictionaries") == 2
    assert "interrupted" in yomitan_sync.get_state()["results"]["dictionaries"]["error"]


def test_running_import_is_not_cleared_while_overlay_reports_busy(sync_dir, monkeypatch):
    _write_dictionaries(sync_dir)
    FakeOverlay(monkeypatch, report={**_report(), "busy": {"settings": False, "dictionaries": True}})
    monkeypatch.setattr(yomitan_sync, "get_config", lambda: SimpleNamespace(general=SimpleNamespace(single_port=7275)))
    yomitan_sync.start_dictionary_import()
    yomitan_sync._state["dictionary_job"]["started_at"] -= 600  # quiet for 10 minutes
    yomitan_sync._watch["connected"] = True
    assert yomitan_sync.watch_once() is None
    time.sleep(0.05)
    assert yomitan_sync.get_state()["dictionary_job"]["running"] is True
