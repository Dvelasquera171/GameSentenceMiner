# GSM line times are local wall-clock values.
# ruff: noqa: DTZ001
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from GameSentenceMiner.web import ask_api, texthooking_page


def _line(i, text):
    return SimpleNamespace(id=f"l{i}", text=text, time=datetime(2026, 10, 4, 20, 0) + timedelta(seconds=i))


def test_recent_lines_skip_blank_and_keep_order():
    lines = [_line(0, "一"), _line(1, "  "), _line(2, "二"), _line(3, "三")]
    assert [x["id"] for x in ask_api.recent_lines(lines, 2)] == ["l2", "l3"]
    assert ask_api.recent_lines(lines, 10)[0] == {"id": "l0", "text": "一", "time": "2026-10-04T20:00:00"}
    assert ask_api.recent_lines([], 5) == []


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__, template_folder=str(Path(texthooking_page.__file__).parent / "templates"))
    ask_api.register_ask_routes(app)
    app.config["TESTING"] = True
    monkeypatch.setattr(ask_api, "_current_game", lambda: "NEKOPARA vol.1")
    return app.test_client()


def test_recent_lines_route_clamps_count(client, monkeypatch):
    lines = [_line(i, f"行{i}") for i in range(150)]
    monkeypatch.setattr("GameSentenceMiner.util.text_log.get_all_lines", lambda: lines)
    data = client.get("/api/ask/recent-lines?count=500").json
    assert data["game"] == "NEKOPARA vol.1"
    assert len(data["lines"]) == ask_api.MAX_RECENT_LINES and data["lines"][-1]["id"] == "l149"
    assert len(client.get("/api/ask/recent-lines?count=x").json["lines"]) == 30


def test_ask_page_renders(client):
    page = client.get("/ask")
    assert page.status_code == 200
    assert b"/static/js/ask.js" in page.data and b'id="question"' in page.data


def test_recent_lines_are_titled_after_the_newest_line(client, monkeypatch):
    lines = [_line(0, "ゲーム"), _line(1, "動画")]
    lines[0].scene, lines[1].scene = "NEKOPARA vol.1", "Frieren"
    monkeypatch.setattr("GameSentenceMiner.util.text_log.get_all_lines", lambda: lines)
    assert client.get("/api/ask/recent-lines").json["game"] == "Frieren"
    assert ask_api.title_for_lines([]) == ""
