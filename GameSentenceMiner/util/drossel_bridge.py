"""Reading counts in Drossel: GSM reading sessions become Drossel pomodoro sessions.

Drossel (the owner's pomodoro app) syncs through a relay that keeps one envelope of records per
device and merges them (union, last-write-wins per id, deletions as tombstones). GSM publishes
its own envelope to the ``sessions`` collection, so every Drossel device sees each reading
session as a completed work session in the chosen category (default "JP Immersion"), named after
the game/anime/manga: EXP, streaks and dailies count reading without starting a timer.

* Ids are derived from the GSM session, so two PCs with the same synced history publish the same
  records, not doubles.
* Duration is GSM's own reading-time estimate (idle gaps not counted), as in GSM's stats.
* A session that overlaps a Drossel timer session in the same category is skipped: the timer
  already counted that time.
* Sessions that disappear (lines deleted) are published as tombstones.

The relay URL and secret are read from Drossel's settings on this PC; nothing secret is stored
in GSM's config.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests

from GameSentenceMiner.util.config.configuration import get_config, logger

DROSSEL_SETTINGS = Path(os.environ.get("APPDATA", "")) / "Tomatenuhr von Flügel" / "data" / "settings.json"
DEFAULT_CATEGORY = "JP Immersion"
LOOKBACK_SECONDS = 60 * 24 * 3600
MIN_SESSION_SECONDS = 120
OVERLAP_SHARE = 0.5
INTERVAL_SECONDS = 600
ID_PREFIX = "gsm-"


def load_drossel_relay(path: Path = DROSSEL_SETTINGS) -> Optional[tuple[str, str]]:
    """(relay URL, secret) from Drossel's settings on this PC, or None when it has no relay."""
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = str(settings.get("syncUrl") or "").strip().rstrip("/")
    secret = str(settings.get("syncSecret") or "").strip()
    return (url, secret) if url.startswith("https://") and secret else None


def device_id(host: Optional[str] = None) -> str:
    name = re.sub(r"[^A-Za-z0-9-]", "-", host or socket.gethostname()).strip("-") or "pc"
    return f"gsm-{name}"[:64]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def session_record_id(game_key: str, start_ts: float) -> str:
    return ID_PREFIX + hashlib.sha1(f"{game_key}|{int(start_ts)}".encode("utf-8")).hexdigest()[:24]


def category_id(envelopes: Iterable[dict], name: str) -> Optional[str]:
    """The live Drossel category with this name, after merging every device's copy."""
    merged: dict[str, dict] = {}
    for envelope in envelopes:
        for record in envelope.get("records") or []:
            if isinstance(record, dict) and record.get("id"):
                current = merged.get(record["id"])
                if current is None or str(record.get("updatedAt") or "") > str(current.get("updatedAt") or ""):
                    merged[record["id"]] = record
    wanted = name.strip().casefold()
    for record in merged.values():
        if (
            str(record.get("name") or "").strip().casefold() == wanted
            and not record.get("archived")
            and not record.get("deletedAt")
        ):
            return record["id"]
    return None


def _timer_intervals(envelopes: Iterable[dict], category: str) -> list[tuple[float, float]]:
    """Drossel's own work sessions in the category (not ours), as (start, end) epoch seconds."""
    intervals = []
    for envelope in envelopes:
        for record in envelope.get("records") or []:
            if (
                not isinstance(record, dict)
                or str(record.get("id", "")).startswith(ID_PREFIX)
                or record.get("deletedAt")
                or record.get("type") != "work"
                or record.get("categoryId") != category
            ):
                continue
            try:
                start = datetime.fromisoformat(str(record["startedAt"]).replace("Z", "+00:00")).timestamp()
                intervals.append((start, start + float(record.get("durationSec") or 0)))
            except (KeyError, ValueError):
                continue
    return intervals


def _overlaps_timer(start: float, end: float, intervals: list[tuple[float, float]]) -> bool:
    span = max(1.0, end - start)
    covered = sum(max(0.0, min(end, b) - max(start, a)) for a, b in intervals)
    return covered / span >= OVERLAP_SHARE


def build_records(
    sessions: Iterable[dict],
    category: str,
    previous: dict[str, dict],
    timer_intervals: list[tuple[float, float]],
    now_iso: str,
) -> list[dict]:
    """Records to publish: current sessions plus tombstones for ones that are gone.

    ``sessions`` items: {game_key, title, start_ts, end_ts, seconds, lines, chars}.
    ``previous``: our last published records by id; unchanged records keep their updatedAt.
    """
    records: dict[str, dict] = {}
    for session in sessions:
        seconds = int(round(session["seconds"]))
        if seconds < MIN_SESSION_SECONDS or _overlaps_timer(session["start_ts"], session["end_ts"], timer_intervals):
            continue
        record = {
            "id": session_record_id(session["game_key"], session["start_ts"]),
            "categoryId": category,
            "subName": str(session["title"])[:80],
            "type": "work",
            "startedAt": iso(session["start_ts"]),
            "durationSec": seconds,
            "plannedSec": seconds,
            "completed": True,
            "note": f"GSM · {session['lines']} lines · {session['chars']} chars",
            "deletedAt": None,
        }
        old = previous.get(record["id"])
        unchanged = old is not None and {k: v for k, v in old.items() if k != "updatedAt"} == record
        record["updatedAt"] = old["updatedAt"] if unchanged else now_iso
        records[record["id"]] = record
    for record_id, old in previous.items():
        if record_id not in records:
            if old.get("deletedAt"):
                records[record_id] = old
            else:
                records[record_id] = {**old, "deletedAt": now_iso, "updatedAt": now_iso}
    return sorted(records.values(), key=lambda r: r["id"])


def gsm_reading_sessions(now: float, lookback: float = LOOKBACK_SECONDS) -> list[dict]:
    """Every GSM reading session that started within the lookback, with GSM's reading-time estimate."""
    from GameSentenceMiner.util import reading_sessions
    from GameSentenceMiner.util.database.db import GameLinesTable
    from GameSentenceMiner.web.stats import calculate_actual_reading_time

    games = GameLinesTable._db.fetchall(
        f"SELECT COALESCE(NULLIF(game_id, ''), game_name), game_name FROM {GameLinesTable._table} "
        f"WHERE timestamp >= ? GROUP BY COALESCE(NULLIF(game_id, ''), game_name)",
        (now - lookback,),
    )
    result = []
    for game_key, game_name in games:
        for session in reading_sessions.list_sessions(str(game_key), limit=100_000):
            if session.start_ts < now - lookback:
                continue
            lines = reading_sessions.get_session_lines(session.game_key, session.start_ts, session.end_ts)
            seconds = calculate_actual_reading_time(
                [float(ln.timestamp) for ln in lines], [str(ln.line_text or "") for ln in lines]
            )
            result.append(
                {
                    "game_key": session.game_key,
                    "title": session.game_name or str(game_name or ""),
                    "start_ts": session.start_ts,
                    "end_ts": session.end_ts,
                    "seconds": seconds,
                    "lines": session.line_count,
                    "chars": session.char_count,
                }
            )
    return result


class DrosselRelay:
    def __init__(self, url: str, secret: str, timeout: float = 20.0):
        self.url, self.secret, self.timeout = url.rstrip("/"), secret, timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}

    def envelopes(self, collection: str) -> list[dict]:
        response = requests.get(f"{self.url}/v1/{collection}", headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []

    def publish(self, collection: str, device: str, records: list[dict]) -> None:
        envelope = {"device": device, "savedAt": iso(time.time()), "records": records}
        response = requests.put(
            f"{self.url}/v1/{collection}/{device}", headers=self._headers(), json=envelope, timeout=self.timeout
        )
        response.raise_for_status()


def sync_once(
    relay: DrosselRelay,
    category_name: str,
    device: str,
    sessions_provider: Callable[[float], list[dict]] = gsm_reading_sessions,
    now: Optional[float] = None,
) -> dict:
    now = time.time() if now is None else now
    category = category_id(relay.envelopes("categories"), category_name)
    if category is None:
        return {"status": "error", "error": f'No Drossel category named "{category_name}".'}
    envelopes = relay.envelopes("sessions")
    previous = {
        r["id"]: r
        for e in envelopes
        if e.get("device") == device
        for r in e.get("records") or []
        if isinstance(r, dict) and str(r.get("id", "")).startswith(ID_PREFIX)
    }
    records = build_records(sessions_provider(now), category, previous, _timer_intervals(envelopes, category), iso(now))
    changed = records != sorted(previous.values(), key=lambda r: r["id"])
    if changed:
        relay.publish("sessions", device, records)
    live = sum(1 for r in records if not r.get("deletedAt"))
    return {"status": "success", "published": changed, "sessions": live}


_thread: Optional[threading.Thread] = None
_last_result: dict = {"status": "never_ran"}


def last_result() -> dict:
    return dict(_last_result)


def run_now() -> dict:
    global _last_result
    advanced = get_config().advanced
    if not getattr(advanced, "drossel_reading_sync", False):
        _last_result = {"status": "disabled"}
        return last_result()
    relay = load_drossel_relay()
    if relay is None:
        _last_result = {"status": "error", "error": "Drossel has no relay set up on this PC."}
        return last_result()
    try:
        _last_result = sync_once(
            DrosselRelay(*relay),
            str(getattr(advanced, "drossel_category", "") or DEFAULT_CATEGORY),
            device_id(),
        )
    except requests.RequestException as exc:
        _last_result = {"status": "error", "error": f"Drossel relay: {exc.__class__.__name__}"}
    except Exception as exc:  # noqa: BLE001 - a bridge failure must never disturb GSM
        logger.exception("Drossel bridge failed")
        _last_result = {"status": "error", "error": str(exc)}
    _last_result["at"] = time.time()
    if _last_result["status"] == "error":
        logger.warning(f"Drossel: {_last_result['error']}")
    return last_result()


def start_background_sync(interval: float = INTERVAL_SECONDS) -> None:
    """Publish every ``interval`` seconds while GSM runs (only does work when enabled)."""
    global _thread
    if _thread is not None:
        return

    def loop():
        while True:
            time.sleep(interval)
            run_now()

    _thread = threading.Thread(target=loop, name="drossel-bridge", daemon=True)
    _thread.start()
