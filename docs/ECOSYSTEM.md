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
| D | Non-game sources (anime, manga, YouTube): GSM Connect | done | local agent |
| F | Deploy to a second PC with few clicks | small | jp-mining-tools scripts |
| H | One-click session start from the GSM Home tab | small | local agent, after E |

Everything below is a plan, not a contract. Additive API fields are fine; a new table, a changed
API shape, or any write to Anki needs the owner's OK first.

### Decisions taken (2026-10-04)
- **Y merge rule:** the overlay syncs dictionaries, Anki card formats, translation, parsing and
  audio from the Firefox export and keeps its own scanning/popup/input settings. Card consistency
  is the hard requirement: the health page must assert that the overlay's and Firefox's Anki card
  formats (deck, model, field mapping) are identical after a sync, and fail the row if not.
- **Health page AI row** runs the test call only on explicit Re-check, never on page load.

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

**Ingest side: done (2026-10-05) with GSM Connect**, a small browser extension in `gsm_connect/`
(see its README). Research first:
1. *asbplayer* only accepts commands over its websocket (mine, load, seek, get-subtitles); it
   never pushes the current line. Its only outbound path is "auto-copy to clipboard", which needs
   page focus and takes over the clipboard. So the extension reads the subtitle on screen instead
   (`span[data-asb-subtitle-index]` outside its subtitle list, first track by default).
2. *Manatan* (manga OCR + anime player, a local web app on `127.0.0.1:4568`) renders manga text
   as `.gemini-ocr-text-box` per page and anime subtitles as `[data-subtitle-cue]`; the extension
   reads both. mokuro HTML pages too.
3. *YouTube*: the captions on screen (`.ytp-caption-segment`); no caption download.

GSM side: `POST /api/connect/lines` (`web/connect_api.py`), source kind `browser`, each line filed
under its own title (`metadata.scene` → `game_name`), so the title override is per line rather
than a global setting. Cards mined from browser lines keep the browser's media (no OBS). The
extension queues lines while GSM is closed. No anime-specific code in GSM beyond the source kind.

---

### How anime and manga would actually flow
- **Anime, two routes.** (a) *mpv + mpv_websocket* (the usual mining setup): the script emits
  each subtitle line over a websocket; GSM adds that port as a text source and everything else
  already works. Near-zero GSM work. (b) *asbplayer in the browser*: verify whether its websocket
  integration can push the current subtitle out; if not, a small bridge or route (a) is the
  answer. In both cases asbplayer/mpv already make audio+image cards, so GSM must **not** add OBS
  replay media to those cards: a per-source rule "log and translate only, no media" is needed
  (field policy already has coalesce/overwrite modes; this adds a source-level switch).
- **Manga:** manatan (or mokuro/manga-ocr) → clipboard → GSM clipboard source → lines filed under
  the title override. Cards come from Yomitan on the texthooker page as usual. No screenshots
  from GSM (there is no OBS scene); the Picture field stays Yomitan's.
- **Sessions:** the title override plus the manual Start/End buttons give one session per
  episode or chapter; the gap rule still splits long pauses.

## H. One-click session start (fewer clicks, one hub)
Today a session is: start Luna, attach to the game, start GSM, start OBS, open the texthooker in
Firefox, start Anki. GSM's Home/Launcher tab already launches a game with its OBS scene and can
launch Agent alongside it. Extend that into one **Start session** action per game profile:
1. launch the game (existing), 2. launch LunaTranslator and, where Luna supports it, auto-attach
to the process (research Luna's command line / `userconfig` autostart options), 3. start Anki if
not running (path setting), 4. open the texthooker in the configured browser (Firefox path
setting; today GSM uses the system default), 5. start a manual reading session
(`POST /api/review/sessions/start`), 6. show the health summary from E. Stop session reverses
1 and 5 and, once Session Review is done, offers "Generate review".
The hub is therefore the GSM Home tab for starting/stopping and the Flask pages in Firefox for
reading, review and setup. Nothing new to install.

## F. Deploy to a second PC with few clicks
Two parts.
- **App:** do not run from source on the laptop. Build the installer once on the desktop
  (`npm run app:dist`), install that on the laptop; keep source-based development on the desktop
  only. Avoids Rust/VS Build Tools on the laptop.
- **Config:** `jp-mining-tools` already holds redacted snapshots of every config. Add
  `scripts/apply_setup.py` there: writes GSM `config.json` (the profile, secrets from environment
  variables, never from the repo), Luna's `userconfig/config.json` (hooker-only, websocket on),
  pushes the Lapis note type to Anki via AnkiConnect if missing (templates are in the snapshot;
  warn about the one-way AnkiWeb sync), and prints the two Yomitan import clicks (settings +
  dictionary collection; Firefox cannot be driven from outside). Verification is the health page
  from E. Plan it after E lands.
