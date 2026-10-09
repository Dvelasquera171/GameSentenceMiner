from __future__ import annotations

import json
from types import SimpleNamespace

from GameSentenceMiner.util import drossel_bridge as db

NOW = 1_791_500_000.0
NOW_ISO = db.iso(NOW)
JP = "20fb612a-7f72-4faa-a762-e698eb3f58c4"


def session(start, seconds=1500, title="Azumanga Daioh", key="c1ede634"):
    return {
        "game_key": key,
        "title": title,
        "start_ts": start,
        "end_ts": start + seconds + 60,
        "seconds": seconds,
        "lines": 120,
        "chars": 2400,
    }


def test_relay_settings_come_from_drossel(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"syncUrl": "https://tomatenuhr-sync.example.workers.dev/", "syncSecret": "s3cret"}),
        encoding="utf-8",
    )
    assert db.load_drossel_relay(path) == ("https://tomatenuhr-sync.example.workers.dev", "s3cret")
    path.write_text(json.dumps({"syncUrl": "", "syncSecret": ""}), encoding="utf-8")
    assert db.load_drossel_relay(path) is None
    assert db.load_drossel_relay(tmp_path / "missing.json") is None


def test_device_id_fits_the_relay_rules():
    assert db.device_id("DESKTOP_1 (main)") == "gsm-DESKTOP-1--main"
    assert len(db.device_id("x" * 200)) == 64


def test_category_is_found_by_name_after_merging_devices():
    envelopes = [
        {"device": "a", "records": [{"id": JP, "name": "JP Immersion", "archived": False, "updatedAt": "2026-08-01"}]},
        {
            "device": "b",
            "records": [{"id": "old", "name": "JP Immersion", "archived": True, "updatedAt": "2026-08-02"}],
        },
    ]
    assert db.category_id(envelopes, " jp immersion ") == JP
    assert db.category_id(envelopes, "Piano") is None


def test_records_are_completed_work_sessions_named_after_the_title():
    [record] = db.build_records([session(NOW - 3600)], JP, {}, [], NOW_ISO)
    assert record == {
        "id": db.session_record_id("c1ede634", NOW - 3600),
        "categoryId": JP,
        "subName": "Azumanga Daioh",
        "type": "work",
        "startedAt": db.iso(NOW - 3600),
        "durationSec": 1500,
        "plannedSec": 1500,
        "completed": True,
        "note": "GSM · 120 lines · 2400 chars",
        "deletedAt": None,
        "updatedAt": NOW_ISO,
    }


def test_short_sessions_and_time_a_drossel_timer_covered_are_skipped():
    timer = [(NOW - 3700, NOW - 3700 + 1500)]
    records = db.build_records(
        [session(NOW - 3600), session(NOW - 9000, seconds=60), session(NOW - 20000)], JP, {}, timer, NOW_ISO
    )
    assert [r["startedAt"] for r in records] == [db.iso(NOW - 20000)]


def test_unchanged_records_keep_their_stamp_and_gone_ones_become_tombstones():
    first = db.build_records([session(NOW - 3600), session(NOW - 20000)], JP, {}, [], "2026-10-01T00:00:00.000Z")
    previous = {r["id"]: r for r in first}
    later = db.build_records([session(NOW - 3600)], JP, previous, [], NOW_ISO)
    kept = next(r for r in later if r["startedAt"] == db.iso(NOW - 3600))
    gone = next(r for r in later if r["startedAt"] == db.iso(NOW - 20000))
    assert kept["updatedAt"] == "2026-10-01T00:00:00.000Z" and kept["deletedAt"] is None
    assert gone["deletedAt"] == NOW_ISO and gone["updatedAt"] == NOW_ISO

    # A session that grew while reading gets a fresh stamp.
    grown = db.build_records([session(NOW - 3600, seconds=1800)], JP, previous, [], NOW_ISO)
    assert next(r for r in grown if not r["deletedAt"])["updatedAt"] == NOW_ISO


class FakeRelay:
    def __init__(self, categories, sessions):
        self.collections = {"categories": categories, "sessions": sessions}
        self.published = []

    def envelopes(self, collection):
        return self.collections[collection]

    def publish(self, collection, device, records):
        self.published.append((collection, device, records))
        envelope = {"device": device, "records": records}
        self.collections[collection] = [e for e in self.collections[collection] if e["device"] != device] + [envelope]


def test_sync_publishes_only_when_something_changed():
    relay = FakeRelay([{"device": "phone", "records": [{"id": JP, "name": "JP Immersion"}]}], [])
    provider = lambda now: [session(NOW - 3600)]  # noqa: E731

    first = db.sync_once(relay, "JP Immersion", "gsm-desk", provider, now=NOW)
    assert first == {"status": "success", "published": True, "sessions": 1}
    second = db.sync_once(relay, "JP Immersion", "gsm-desk", provider, now=NOW + 600)
    assert second["published"] is False
    assert len(relay.published) == 1 and relay.published[0][1] == "gsm-desk"


def test_sync_reports_a_missing_category():
    relay = FakeRelay([], [])
    result = db.sync_once(relay, "JP Immersion", "gsm-desk", lambda now: [], now=NOW)
    assert result["status"] == "error" and "JP Immersion" in result["error"]


def test_run_now_is_off_until_enabled(monkeypatch):
    monkeypatch.setattr(db, "get_config", lambda: SimpleNamespace(advanced=SimpleNamespace(drossel_reading_sync=False)))
    assert db.run_now()["status"] == "disabled"


def test_gsm_sessions_use_gsms_reading_time_and_skip_old_ones(monkeypatch):
    from GameSentenceMiner.util import reading_sessions
    from GameSentenceMiner.util.database.db import GameLinesTable
    from GameSentenceMiner.web import stats

    recent = SimpleNamespace(
        game_key="g1", game_name="Azumanga Daioh", start_ts=NOW - 3600, end_ts=NOW - 1800, line_count=2, char_count=10
    )
    old = SimpleNamespace(
        game_key="g1",
        game_name="Azumanga Daioh",
        start_ts=NOW - 90 * 86400,
        end_ts=NOW - 90 * 86400 + 60,
        line_count=1,
        char_count=3,
    )
    lines = [
        SimpleNamespace(timestamp=NOW - 3600, line_text="一行目"),
        SimpleNamespace(timestamp=NOW - 1800, line_text="二行目"),
    ]
    monkeypatch.setattr(GameLinesTable._db, "fetchall", lambda *_a, **_k: [("g1", "Azumanga Daioh")])
    monkeypatch.setattr(reading_sessions, "list_sessions", lambda key, limit: [recent, old])
    monkeypatch.setattr(reading_sessions, "get_session_lines", lambda key, start, end: lines)
    monkeypatch.setattr(stats, "calculate_actual_reading_time", lambda ts, texts: 900.0)

    assert db.gsm_reading_sessions(NOW) == [
        {
            "game_key": "g1",
            "title": "Azumanga Daioh",
            "start_ts": NOW - 3600,
            "end_ts": NOW - 1800,
            "seconds": 900.0,
            "lines": 2,
            "chars": 10,
        }
    ]
