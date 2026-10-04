# One ecosystem: GSM + LunaTranslator + Yomitan + Anki

Owner's direction (2026-10-04): the tools should behave as one system with one place to see
whether it works, deployable to a second machine with few clicks. Learning features
(Session Review) ride on top of that; they are not the unification work itself.

Owner's real setup (redacted copies live in the `jp-mining-tools` repo under `snapshots/`):
Luna hooks text → `ws://localhost:2333` → GSM (texthooker on `:55000`) opened in **Firefox**;
Firefox Yomitan (the only "real" one) creates Lapis cards in deck `General Mining`; GSM adds
`SentenceAudio`, `Picture`, `SentenceTranslation` (AI: GSM OpenAI provider → NanoGPT,
`deepseek/deepseek-v4-pro-0813`, backup `deepseek-v4-flash`). The GSM overlay has a second
Yomitan in `%APPDATA%\gsm_overlay`.

## Roadmap (reordered)

| # | Item | Size | Who |
|---|---|---|---|
| E | Setup health page | small | local agent |
| Y | One Yomitan: overlay syncs from the Firefox export | medium | local agent |
| Q | Extend texthooker AI help (follow-ups, wider context) | small | local agent |
| A/B/C | Finish Session Review (page, session buttons, prompt tuning) | medium | local agent, see SESSION_REVIEW.md |
| D | Non-game sources (anime, manga) | small + research | local agent |
| F | Deploy to a second PC with few clicks | small | jp-mining-tools scripts |

Everything below is a plan, not a contract. Additive API fields are fine; a new table, a changed
API shape, or any write to Anki needs the owner's OK first.

---

## E. Setup health page

### What exists
- `/get_status` already returns `anki_connected`, `anki_beacon_connected`, `obs_connected`,
  `websockets_connected` (a dict keyed by source URL, so Luna on `localhost:2333` is visible),
  `text_runtime` and `transport_runtime` health. The Electron Home tab shows badges from it;
  the first-run `SetupWizard` pings Anki and OBS.
- `anki_setup.find_anki_field_mismatch` detects missing fields, but only when a card arrives.
- There is no AI "test connection" anywhere, and nothing checks the note type up front.

### Build
A Flask endpoint `GET /api/setup-check` returning `{"checks": [...]}` and a page
`/setup-check` that renders it with a Re-check button. Flask (not Electron) so it works from
Firefox and from any machine on the LAN, needs no build step, and the Home tab can later embed
or call the same endpoint. Each check: `id, title, status (ok|warn|fail|skip), detail, fix`.

| Check | How | Fix text when failing |
|---|---|---|
| Text source: Luna | `gsm_status.websockets_connected` contains the `2333` URI; also show the configured source list and which are connected | "Start LunaTranslator and open a game; in Luna, Settings → Network → WebSocket must be on (`network_websocket`), port 2333. In GSM, Settings → Text sources must list `localhost:2333`." |
| Any line received recently | `gsm_status.last_line_received` age | "Hook the game in Luna; text should appear on the texthooker page." |
| Texthooker reachable | the request itself proves it; show the URL to open in Firefox | |
| AnkiConnect | `invoke("version")` with 1 s timeout (reuse `anki.refresh_anki_connect_connection_status`) | "Start Anki. AnkiConnect must be installed (add-on 2055492159) and allow `http://127.0.0.1:8765`." |
| Deck exists | `deckNames` contains the deck from the Yomitan/Anki config (GSM config has `anki.note_type`; deck comes from the Yomitan export, so just report the decks found) | |
| Note type and fields | `modelFieldNames(note_type)` ⊇ every configured GSM field: `anki.sentence_field, sentence_audio_field, picture_field, word_field, sentence_furigana_field, game_name_field, previous_*`, plus `ai.anki_field` when `ai.add_to_anki`. Report each missing field by name | "In Anki: Tools → Manage Note Types → Lapis → Fields → Add `<name>`. Warning: adding a field forces a one-way AnkiWeb sync." |
| Config field list stale | GSM `anki.available_fields` differs from live `modelFieldNames` (the owner's snapshot lacks `SentenceTranslation`) | "Open GSM Settings → Anki and press Refresh fields." |
| Yomitan → Anki path | `findNotes("note:Lapis added:7")` count; warn if 0 | "Mine one word from the texthooker in Firefox; a Lapis note should appear." |
| AI configured | `get_config().ai.is_configured()` | "Settings → AI: provider OpenAI, URL `https://nano-gpt.com/api/v1`, model, API key." |
| AI reachable | `AIService.generate_raw_prompt("Reply with OK.", request_kind="health", max_tokens=5)` with the configured provider; report model and latency; run only on explicit Re-check to avoid spending tokens on page load | surface the provider error text (401 → key, 404 → model name, timeout → URL/network) |
| OBS | `obs_connected`; `warn` not `fail`, since audio/screenshots need it but reading does not | "Settings → OBS: start OBS or enable GSM's bundled OBS." |

Also: a one-line summary at the top ("4 ok, 1 warn, 1 fail") and a link from the texthooker
navigation. Later, the Electron Home tab can show the same summary by calling the endpoint.

Files: `GameSentenceMiner/web/setup_check_api.py` (new, registered in `web/__init__.py`),
`web/templates/setup_check.html`, `web/static/js/setup_check.js`, tests in
`tests/web/test_setup_check_api.py` with AnkiConnect and AI mocked.

### Owner test
Open `http://localhost:55000/setup-check` with everything running: all ok. Close Anki → Anki
rows fail with the fix text; start Anki → Re-check → ok. Put a wrong key in the AI tab →
Re-check → "AI reachable" fails with a 401 message. Close Luna → Luna row fails.

---

## Y. One Yomitan

### Facts
- The overlay (`GSM_Overlay/main.js`) runs its own Chromium build of Yomitan with its own
  profile dir (`%APPDATA%\gsm_overlay`). Firefox's extension data is private to Firefox; there
  is no supported way to read it from outside, and the overlay cannot load a Firefox extension.
  So "literally one install" is not possible. "One source of truth" is.
- GSM already has a channel to drive the overlay's Yomitan settings:
  Python `util/anki_yomitan.py` → overlay message `anki-setup-yomitan` → `GSM_Overlay/anki_setup.js`
  → Yomitan `API.getSettings/setAllSettings` in a hidden settings window. That is the mechanism to
  extend.
- Yomitan's Settings export JSON (the owner's `snapshots/yomitan/firefox-settings.json`) is exactly
  what `setAllSettings` takes. The vendored Yomitan also has `dictionary-importer.js` and
  `backup-controller.js` (dictionary collection export/import).

### Build: Firefox is the source of truth; the overlay syncs from its export
1. Owner-side export (manual, two clicks, whenever Firefox's Yomitan changes): Firefox Yomitan →
   Settings → Backup → **Export Settings** and **Export Dictionary Collection** into
   `%APPDATA%\GameSentenceMiner\yomitan_sync\` (`settings.json`, `dictionaries.zip`).
2. GSM watches that folder. When `settings.json` changes (hash), it sends a new overlay message
   `sync-yomitan-settings` with the JSON. The overlay merges and applies via `setAllSettings`:
   - **take from Firefox:** `dictionaries` (order, enabled, styles), `anki` (card formats,
     deck, model, fields, tags), `translation`, `parsing`, `audio`, `sentenceParsing`.
   - **keep the overlay's own:** `general`, `popupWindow`, `scanning`, `inputs`, `clipboard`,
     `accessibility` (these are tuned for an in-game transparent window and would break if
     copied from a browser profile).
3. When `dictionaries.zip` changes, the overlay imports it through Yomitan's dictionary import
   (background job; it is hundreds of MB). Report progress back on the same channel.
4. The health page gets a row "Overlay Yomitan: synced from export of <date>" / "export is
   newer than last sync" / "no export found", with the fix being the two export clicks.
5. Settings → Overlay gets a "Sync Yomitan from Firefox export now" button (reuses step 2).

What this buys: dictionaries, Anki mapping and glossary behaviour identical in game and in
Firefox, with one manual export when something changes. What it does not do: sync Firefox from
the overlay (by design; Firefox is the master) or sync automatically without the export.

Alternative considered and rejected: reading Firefox's IndexedDB (`storage/default/moz-extension+++*/idb`)
directly. Undocumented, Snappy-compressed, multi-GB, breaks on Firefox updates.

Files: `GameSentenceMiner/util/yomitan_sync.py` (watch + hash + send, modelled on
`anki_yomitan.py`), `GSM_Overlay/yomitan_sync.js` (merge + apply + import, modelled on
`anki_setup.js`; GSM-side file, never edit `GSM_Overlay/yomitan/`), a message type pair in
`web/overlay_handler.py`, a button in `ui/config/tabs/overlay.py`, tests for the merge rules.

### Owner test
Export both files from Firefox into the sync folder. Start the overlay. In the overlay's Yomitan
settings, the dictionary list and Anki card format should match Firefox (Kanjium pitch and the
new Jitendex present once Firefox has them). Hover a word in game: pitch shows. Health page
row reads "synced". Change dictionary order in Firefox, export again → row says "export is
newer" → press Sync → order updates.

---

## Q. Texthooker AI help: extend, don't rebuild

### What exists
Each texthooker line has an AI button that opens `AIHelp.svelte` → `POST /analyze-line` with
`mode` ∈ sentence | grammar | vocabulary | nuance | context | **custom** (free-form question)
and the surrounding dialogue (`ai.dialogue_context_length`, 10 lines each side). It uses the
configured provider, so NanoGPT already answers. This covers "why is this particle here?" and
"what does this mean in context?" today.

### Gaps vs the owner's need, and additive fixes
1. **No follow-up.** Each question is one-shot. Add optional `history: [{question, answer}]`
   to `/analyze-line` (ignored when absent, so no shape change) and keep the thread in the
   panel until it is closed. Prompt: prior turns go in as "Earlier in this conversation" data.
2. **Fixed context window.** Add optional `context_lines` (int, or `-1` for the whole current
   session) so a question like "who is 彼 here?" can see more than 10 lines. Default unchanged.
3. **Panel ergonomics.** Keep the panel open after an answer, Enter sends, Shift+Enter newline,
   answers stay readable Japanese (Yomitan works on them). Rebuild with `build_for_gsm.ps1`.
4. Optional later: "Ask about this scene" entry on the Session Review page reusing the same
   endpoint with `context_lines=-1`.

Files: `texthooker/src/components/AIHelp.svelte`, `web/texthooking_page.py` (`analyze_line`),
`ai/service.py` (`analyze`), `ai/prompts/builder.py` (context length override), tests in
`tests/web/test_ai_actions.py` and `tests/ai/test_study_prompts.py`.

### Owner test
On a line, open AI help → Ask a question → "この「は」はなぜ？" → answer. Ask "じゃあ「が」なら？"
→ the answer refers to the first exchange. Set context to "whole session" and ask who a pronoun
refers to.

---

## A/B/C. Session Review
Unchanged; see [SESSION_REVIEW.md](SESSION_REVIEW.md). It runs after E, Y and Q.

---

## D. Anime and manga: where we are

**Review side: done.** Everything in Session Review keys on `game_lines` rows grouped by
`game_id` or `game_name`; the source does not matter.

**Ingest side: 0 of 3.**
1. *Title override* (not started). Lines are named after the OBS scene / foreground window, so
   subtitle or manga text would be filed under whatever GSM thinks the current game is. Needs a
   "current title" setting that `gametext.py` uses for `game_name` when set, plus an input on
   the texthooker. Small.
2. *asbplayer* (not verified). Unknown whether its websocket integration can emit subtitle text
   outward; if not, a tiny bridge (subtitle file + player position → websocket on a port GSM
   already listens to) is the fallback. One hour of research before any code.
3. *manatan / manga OCR* (not verified). If it writes the clipboard, GSM's clipboard source
   already ingests it and only item 1 is needed.

Nothing anime- or manga-specific should go into GSM; only item 1 is GSM code.

---

## F. Deploy to a second PC with few clicks
Not GSM code. The `jp-mining-tools` repo already holds redacted snapshots of every config; the
natural next step there is an `apply_setup.py` that writes GSM `config.json` (profile), Luna's
`userconfig/config.json` (hooker-only, websocket on), and prints the two Yomitan import clicks,
reading secrets from environment variables. Depends on E for verification: run the health page
after applying. Plan it after E lands.
