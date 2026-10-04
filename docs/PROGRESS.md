# Progress: unattended run (2026-10-03/04)

Read this first. Branch `claude/vigilant-meitner-q8xjt5`, everything pushed. Work order came from
[HANDOFF_LOCAL_AGENT.md](HANDOFF_LOCAL_AGENT.md): E → Y → Q → Session Review A/B/C. D and F
were not started (by instruction).

Rules followed: no Anki writes, no Luna config changes, no direct GSM database edits, no edits
under `%APPDATA%`, no API keys anywhere. Exactly **one** NanoGPT call was made (the setup page's
AI test, see E). Every Python change was followed by `ruff format` and
`pytest tests/ai tests/web tests/util/database tests/util/test_reading_sessions.py -q`.

## Status

| Item | Status | Commits |
|---|---|---|
| Pre-existing red tests in the required suite | fixed | `d71385c1` |
| E. Setup health page | done, owner test pending | `84eef80f` |
| Y. Overlay Yomitan sync from Firefox export | in progress | |
| Q. AI help follow-ups + context size | not started | |
| Session Review A / B / C | not started | |

## Needs owner approval

Nothing yet.

## Open questions

Nothing yet.

---

## Pre-existing test failures (fixed)

On a clean checkout the required suite had 3 failures + 7 errors, none caused by this run:
- `tests/web/test_session_review_api.py` (7 errors): the fixture added routes to the shared
  texthooker Flask app, which refuses new routes once an earlier test has served a request.
  The fixture now builds its own app.
- `tests/web/test_settings_modal_templates.py`: `review.html` has the navigation bar but not the
  shared settings modal. Added the include.
- `tests/util/database/test_game_archive.py` (2, order-dependent): the fixture patched
  `archive_files.archive_directory`, but `database_maintenance_api` imported that function by
  name earlier in the run. The fixture now patches both references.

After the fix: `1373 passed, 1 skipped`.

## E. Setup health page — done (`84eef80f`)

**What:** `http://localhost:55000/setup-check` (link "Setup" in the stats/tools navigation bar).
`GET /api/setup-check` returns `{checks: [{id, title, status, detail, fix}], summary, checked_at, ai_tested}`.

Checks: LunaTranslator websocket (`:2333`, plus the list of all configured sources and which are
connected) · text received in the last 15 min · texthooker URL · AnkiConnect · decks · note type
has every field GSM writes to (`Sentence`, `SentenceAudio`, `Picture`, `Expression`,
`SentenceFurigana`, and `SentenceTranslation` because AI → add to Anki is on) · GSM's saved field
list matches Anki (your snapshot's list lacks `SentenceTranslation`, so expect a **warn** until you
press Refresh Fields) · Lapis notes added in the last 7 days · AI configured · AI reachable · OBS.

- All AnkiConnect calls are read-only (`version`, `deckNames`, `modelNames`, `modelFieldNames`, `findNotes`).
- The AI test runs **only** when you press **Re-check**; page load never sends it. A second
  Re-check within 15 s reuses the previous result instead of sending another request.
- Files: `GameSentenceMiner/web/setup_check_api.py`, `web/templates/setup_check.html`,
  `web/static/js/setup_check.js`, `tests/web/test_setup_check_api.py` (25 tests, Anki and AI mocked).

**Verified here:** GSM restarted cleanly (`npm run agent:restart`, exit 0). With Anki and Luna
closed the page showed `3 ok, 1 warn, 2 fail, 5 skip` with the Luna and AnkiConnect rows failing
and their fix text shown. One Re-check: "OpenAI / deepseek/deepseek-v4-pro-0813 answered in 4330 ms".

**Owner test (click by click):**
1. Start Anki, LunaTranslator (attach to a game) and GSM.
2. Firefox → `http://localhost:55000/setup-check`. Expect every row ok except possibly
   "GSM field list up to date" (warn) and "AI reachable" (skip, not tested yet).
3. If "GSM field list up to date" warns: GSM Settings → Anki → **Refresh Fields** → Save. Reload
   the page → ok.
4. Press **Re-check (includes AI test)** → "AI reachable" shows model and latency.
5. Close Anki → reload → "AnkiConnect" fails with the add-on fix text, the four Anki rows below
   it say skip. Start Anki → Re-check → ok again.
6. GSM Settings → AI: change one character of the API key, save → Re-check → "AI reachable"
   fails with "401/403: the provider rejected the API key". Restore the key.
7. Close Luna → reload → "Text source: LunaTranslator" fails with the Luna fix text.
