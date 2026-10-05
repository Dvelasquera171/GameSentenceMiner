from __future__ import annotations

import pytest
from flask import Flask

from GameSentenceMiner.web import connect_api


@pytest.fixture
def ingested():
    return []


@pytest.fixture
def client(ingested, monkeypatch):
    monkeypatch.setattr(connect_api, "_last_activity", {})

    def fake_ingest(payload):
        ingested.append(payload)
        return {"status": "duplicate" if payload["text"] == "dup" else "accepted"}

    app = Flask(__name__)
    connect_api.register_connect_routes(app, ingest=fake_ingest)
    app.config["TESTING"] = True
    return app.test_client()


def test_payload_files_the_line_under_its_title_and_skips_the_game_overlay():
    payload = connect_api.build_ingest_payload(
        {
            "text": " 字幕の一行 ",
            "title": "Frieren",
            "source": "asbplayer",
            "url": "https://www.netflix.com/watch/1",
            "captured_at": "2026-10-05T10:00:00Z",
        }
    )
    assert payload == {
        "text": "字幕の一行",
        "source": "browser",
        "source_display_name": "GSM Connect · asbplayer",
        "source_instance": "connect:asbplayer:Frieren",
        "title": "Frieren",
        "url": "https://www.netflix.com/watch/1",
        "skip_overlay": True,
        "captured_at": "2026-10-05T10:00:00Z",
    }


def test_payload_without_a_title_uses_the_site_and_rejects_empty_text():
    assert connect_api.build_ingest_payload({"text": "x", "source": "youtube"})["title"] == "YouTube"
    assert connect_api.build_ingest_payload({"text": "   ", "source": "youtube"}) is None
    assert connect_api.build_ingest_payload("not a dict") is None


def test_lines_route_reports_one_status_per_line_in_order(client, ingested):
    res = client.post(
        "/api/connect/lines",
        json={
            "lines": [
                {"text": "一", "title": "A", "source": "youtube"},
                {"text": ""},
                {"text": "dup", "source": "youtube"},
            ]
        },
    )
    assert res.status_code == 200
    assert res.json == {"results": ["accepted", "rejected", "duplicate"]}
    assert [p["text"] for p in ingested] == ["一", "dup"]


def test_status_reports_the_last_accepted_line(client):
    assert client.get("/api/connect/status").json == {"ok": True, "last": None}
    client.post("/api/connect/lines", json={"lines": [{"text": "一", "title": "Vlog", "source": "youtube"}]})
    last = client.get("/api/connect/status").json["last"]
    assert last["title"] == "Vlog" and last["site"] == "YouTube"


def test_lines_route_validates_the_body(client):
    assert client.post("/api/connect/lines", json={"nope": 1}).status_code == 400
    too_many = {"lines": [{"text": "x"}] * (connect_api.MAX_LINES_PER_REQUEST + 1)}
    assert client.post("/api/connect/lines", json=too_many).status_code == 413


def test_a_failing_line_is_reported_for_retry_without_losing_the_batch(monkeypatch):
    calls = []

    def flaky(payload):
        calls.append(payload["text"])
        if payload["text"] == "boom":
            raise RuntimeError("runtime busy")
        return {"status": "accepted"}

    app = Flask(__name__)
    connect_api.register_connect_routes(app, ingest=flaky)
    res = app.test_client().post("/api/connect/lines", json={"lines": [{"text": "boom"}, {"text": "ok"}]})
    assert res.json == {"results": ["backpressured", "accepted"]}
    assert calls == ["boom", "ok"]
