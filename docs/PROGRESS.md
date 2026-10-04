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
| Y. Overlay Yomitan sync from Firefox export | done, owner test pending | `a6abc1e6` |
| Q. AI help follow-ups + context size | in progress | |
| Session Review A / B / C | not started | |

## Needs owner approval

Nothing yet.

## Open questions

1. **Y, `general` keys.** The decision said "keep the overlay's own scanning and popup settings".
   I also copy 8 `general.*` keys from Firefox because they change what a card contains:
   `language`, `resultOutputMode`, `glossaryLayoutMode`, `compactTags`, `mainDictionary`,
   `sortFrequencyDictionary`, `sortFrequencyDictionaryOrder`, `averageFrequency`. Every other
   `general` key (popup size, theme, fonts, …) stays the overlay's. Say if any of the 8 should stay
   overlay-owned; it is one list in `GSM_Overlay/yomitan_sync.js` (`CARD_GENERAL_KEYS`).
2. **Y, which overlay profile.** The export's current profile is synced into the overlay's
   *current* profile only (yours is probably `GSM - Lapis` from GSM's Anki setup). Other overlay
   profiles are untouched.

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

## Y. Overlay Yomitan sync from the Firefox export — done (`a6abc1e6`)

**What:** Firefox Yomitan stays the master. You export from Firefox into
`%APPDATA%\GameSentenceMiner\yomitan_sync\` (keep Yomitan's default file names
`yomitan-settings-*.json` / `yomitan-dictionaries-*.json`; `settings.json` / `dictionaries.json`
also work; the newest file wins). GSM pushes them into the overlay's Yomitan.

- **Taken from Firefox:** `dictionaries` (order, enabled, styles), `anki` (card formats, deck,
  model, fields, tags, duplicate rules), `translation`, `parsing`, `audio`, `sentenceParsing`, and
  the 8 card-content `general` keys listed under Open questions.
- **Kept from the overlay:** `popupWindow`, `scanning`, `inputs`, `clipboard`, `accessibility`, all
  other `general` keys, profile name/conditions, other profiles, global settings. Dictionaries only
  the overlay has (GSM Character Dictionary) keep their entry. A non-localhost Anki server in the
  export is ignored (same guard as Yomitan's own import).
- **Card formats are verified:** after applying, the overlay re-reads its settings and the sync
  fails unless every card format equals Firefox's field by field (deck, model, every field's value
  and overwrite mode). The setup page repeats that check independently (row "Overlay Yomitan: Anki
  card formats match Firefox", fails with the exact differences).
- **Dictionaries:** "Export Dictionary Collection" is a Dexie JSON file, not a zip. The overlay
  imports it exactly like Yomitan's "Import Dictionary Collection" (purge, then import), fetched
  from `GET /api/yomitan-sync/dictionaries-file` (localhost only). Progress shows on the setup page.
  After an import, settings are re-applied automatically. The GSM Character Dictionary is removed
  by the purge and comes back the next time the overlay starts.
- **When it runs:** a watcher checks the folder every 10 s while the overlay is connected and syncs
  each new export once (dictionaries first, settings after). Manual: **Sync now** on the setup page,
  or GSM Settings → Overlay → **Sync Yomitan from Firefox export now** (next to **Open sync folder**).
- The overlay records what it applied in `%APPDATA%\gsm_overlay\yomitan_sync_state.json`, so the
  setup page can say "synced" or "export is newer" across restarts.
- In dev the overlay runs in-process from `GSM_Overlay/main.js`, so restarting GSM is enough; no
  overlay build step.
- Files: `GSM_Overlay/yomitan_sync.js` (+ 3 small hooks in `main.js`), `GameSentenceMiner/util/yomitan_sync.py`,
  `web/yomitan_sync_api.py`, `web/overlay_handler.py`, `ui/config/tabs/overlay.py`, `gsm.py` (starts the watcher).
  Tests: `GSM_Overlay/tests/yomitan_sync.test.cjs` (12), `tests/web/test_yomitan_sync.py` (23).

**Verified here:** unit tests only for the overlay part (no overlay was started: that would rewrite
your overlay profile in `%APPDATA%`). The merge was also run against your real
`firefox-settings.json` snapshot: card formats identical after merge, popup and scanning untouched.
GSM restarted cleanly; the setup page shows "No Firefox settings export in …\yomitan_sync" (warn).

**Owner test (click by click):**
1. Firefox → Yomitan icon → ⚙ Settings → **Backup** → **Export Settings**. Then
   **Export Dictionary Collection** (large; wait until the download finishes).
2. GSM Settings → **Overlay** → **Open sync folder** (creates the folder). Move both downloaded
   files into it. Do not rename them.
3. Start the overlay (Yomitan as dictionary) and GSM if not running.
4. Firefox → `http://localhost:55000/setup-check`. Within ~10 s the row "Overlay Yomitan: synced
   from Firefox" says "Dictionary import running (import, n/m rows)". Reload occasionally; it can
   take several minutes. The overlay's lookups are empty while it runs.
5. When it finishes, both Yomitan rows are **ok**: "Synced from yomitan-settings-… into overlay
   profile '…'" and "All N card formats identical, field by field: Expression → General Mining /
   Lapis (22 fields)".
6. Open the overlay's Yomitan settings: dictionary order and the Anki card format match Firefox;
   popup size and scan modifier are still the overlay's.
7. Hover a word in game: dictionaries (and pitch, once Firefox has Kanjium) show. Restart the overlay
   once so the GSM Character Dictionary comes back.
8. Firefox: move a dictionary up, **Export Settings** again into the folder. Within ~10 s the
   overlay picks it up (or the row says the export is newer: press **Sync now**). Order updates.
9. Optional failure check: in the overlay's Yomitan settings change the deck of the Expression card
   format → reload the setup page after 60 s (or press Re-check) → the card-format row **fails**
   naming the deck → **Sync now** → ok.
