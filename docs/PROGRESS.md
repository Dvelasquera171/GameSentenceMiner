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
| Q. AI help follow-ups + context size | done, owner test pending | `cbd77e1d` |
| Session Review A (review page) | done, owner test pending | `3ea8bdf0` |
| Session Review B (session buttons + auto-end) | B.1, B.2 done; B.3 skipped (optional) | `ff089203` |
| Session Review C (AI output quality) | C.3 done; C.1, C.2 wait for your first real run; C.4 dropped (your decision) | `74bad3d5` |
| D, F | not started (by instruction) | |

**Suites at the end:** required Python suite `1420 passed, 1 skipped`; overlay `node --test`
383 passed; texthooker `pnpm test` 13 + 36 passed, `svelte-check` 0 errors. GSM was restarted
with `npm run agent:restart` after every item (exit 0 each time) and is left running.

**Suggested order for your tests:** E (2 min) → Q (5 min) → Session Review B then A (one short
session; generating a review costs NanoGPT tokens) → Y (needs the two Firefox exports; the
dictionary import can take a while).

## Needs owner approval

Nothing pending.

Decided 2026-10-04: **C.4 speaker names dropped.** No `speaker` column; the AI infers who is
talking from the session's context. (The prompts still print `speaker:` if a source ever
provides one; nothing to change.)

## Skipped and why

- **Session Review C.1 / C.2** (tighten prompts, tune `DEFAULT_CHUNK_CHARS`,
  `QUIZ_CHARS_PER_QUESTION`, `MAX_HIGHLIGHTS`): they depend on reading real reviews, and running
  one would spend NanoGPT tokens. Waiting for your feedback from the first run (see the questions
  at the end of the Session Review test steps).
- **Session Review B.3** ("merge with previous" / "split here"): dropped (owner, 2026-10-04).
  The Start/End button is the source of truth for a session: a manual range always wins over
  the automatic gap split.

## Open questions

1. **Session auto-end when the game closes** uses the overlay's window monitor, so it only works
   while the overlay is running. Without the overlay, a session still ends on an OBS scene change
   or with the End button. Is that enough, or should GSM watch the game process itself?

## Decided (2026-10-04)

- **Y `general` keys:** keep copying all 8 card-content keys from Firefox (`CARD_GENERAL_KEYS`).
- **Y profile:** sync into the overlay's active Yomitan profile only.
- **C.4 speaker names:** dropped; the AI infers speakers from context.
- **B.3 merge/split:** dropped; Start/End is the truth for a session.
- **Next:** test E, Q, Session Review and Y first. Then F if a second PC is near, D if anime or
  manga comes first, otherwise H (one-click session start).

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
- In dev GSM starts the overlay as a separate process (`npm run start` in `GSM_Overlay/`, output
  hidden), so it needs `GSM_Overlay/node_modules`. Those were missing on this PC until 2026-10-04,
  which is why the overlay never started (GSM retried every second and logged "launched
  successfully" each time). Installed then; the lockfile was out of sync upstream and is fixed.
  No build step is needed after code changes; restart the overlay.
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

## Q. AI help: follow-ups and context size — done (`cbd77e1d`)

**What:** the texthooker's per-line AI help keeps a conversation.
- `POST /analyze-line` accepts two **optional** fields; without them nothing changes.
  `history`: earlier `[{question, answer}]` turns (up to 20 accepted, last 8 sent to the model,
  each trimmed), passed as "Earlier in this conversation" data. `context_lines`: `0`–`200` lines
  each side, or `-1` = the current reading session (same gap rule as Stats/Session Review, your
  `session_gap_seconds` is 3600; same scene; capped at 20,000 characters, nearest lines kept, so a
  "whole session" question costs at most roughly 15k input tokens).
- Panel: the thread stays until you close it or press **New thread**; a **Follow-up** box under the
  answers (Enter sends, Shift+Enter new line, Enter that confirms IME conversion never sends);
  a **Dialogue context** selector (Default / ±25 / ±50 / Whole session). Answers are plain
  selectable text, so Firefox Yomitan works on them.
- Texthooker header: new stethoscope icon → opens `/setup-check`.
- Texthooker rebuilt with `build_for_gsm.ps1` (pnpm 11.9.0, the version pinned in
  `texthooker/package.json`, was installed into a temp folder only for the build; nothing global).
- Files: `ai/prompts/builder.py` (`format_conversation_history`, `select_session_lines`),
  `ai/service.py`, `ai/ai_prompting.py`, `web/texthooking_page.py`, `texthooker/src/components/AIHelp.svelte`,
  `App.svelte`, built `web/templates/index.html`. Tests: 13 new Python tests, 2 new + 2 updated vitest
  tests (texthooker suite 33/33).

**Verified here:** GSM restarted cleanly and serves the new texthooker; an invalid
`context_lines` is rejected before any AI call. No AI call was made for Q.

**Owner test (click by click):**
1. Firefox → `http://localhost:55000`. Hook a game so a few lines appear.
2. On a line: **⋯ (More line actions)** → **Ask AI**. Choose **Ask a question**, type
   `この「は」はなぜ？`, press Enter → an answer appears.
3. In **Follow-up** type `じゃあ「が」なら？`, Enter → the answer refers to the first exchange.
4. While typing with the Japanese IME, Enter only confirms the conversion; a second Enter sends.
   Shift+Enter inserts a new line.
5. Set **Dialogue context** to **Whole session**, ask who a pronoun (彼/あいつ) refers to → the
   answer uses lines from earlier in the session.
6. **New thread** clears the conversation. The stethoscope icon in the header opens Setup Check.

## Session Review A / B / C

### A. Review page — done (`3ea8bdf0`)
`http://localhost:55000/review` (new **Review** link in the navigation bar).
- Layout on the existing dashboard CSS. Japanese is visible and plain selectable text (Firefox
  Yomitan works on it); English is always in a collapsed "English" section, including grade
  feedback, correction notes and reference answers.
- While generating: spinner with stage and `n/m` (digest 2/5, quiz 8/12), polling every 3 s.
  Failed reviews show the provider error and a **Retry** button (same time range, new review).
- Quiz: Ctrl+Enter or 採点 grades (one AI call per answer, spinner per question). After a grade:
  verdict + score, Japanese feedback, ✎ corrections, 模範解答 and 参考解答 (the reference answer
  stored with the question). 過去の解答 (n) lists every earlier attempt; the header shows
  "回答済み n/m · 平均 x点" (best score per question). The last grade is shown again on reload.
- Highlight cards: **Copy line** and **Find in Search** (`/search?q=<quote>`).
- Links like `/review?game_key=…&review=12` reopen a review.
- Verified with a throwaway preview server (temporary database, fake grader, port 5099, your data
  untouched): done/running/failed states, grading, history and score all behaved as described.

### B. Session boundaries — B.1, B.2 done (`ff089203`)
- **Texthooker header:** a **▶ Session** button. Click = start a manual session for GSM's current
  game; it then reads "■ <game> · n min". Click again = end every open session; a **Review →**
  link appears that opens the review page for that game. Errors (e.g. no current game) show next to it.
- **Auto-end:** an OBS scene change closes open manual sessions of other games. With the overlay
  running, a game window that has been gone for 60 s closes that game's sessions (a restart or
  loading screen shorter than that keeps the session).
- Texthooker rebuilt; files: `texthooker/src/components/SessionControls.svelte`, `App.svelte`,
  `util/reading_sessions.py` (`end_sessions_on_game_change`, `end_sessions_for_game`),
  `obs/service.py`, `util/platform/windows_window_monitor.py`.

### C. Output quality — C.3 done (`74bad3d5`)
- After generation, a consistency pass checks the AI output against the session: a highlight
  must quote a real line (a wrong `line_id` is repaired when the quote is found in another line;
  an invented quote is dropped); quiz questions citing only nonexistent lines are dropped (never
  all of them). What it changed is written to the GSM log ("Session review consistency pass").
- C.1/C.2: see "Skipped" above. C.4 (speaker names): dropped by decision; the AI infers speakers from context.

### Owner test (click by click)
1. Firefox → `http://localhost:55000` (texthooker). Top right: **▶ Session** → it turns into
   "■ <game> · 0 min". Read a few lines. Click it → it ends and **Review →** appears; click that.
2. On the review page the game is preselected; the sessions table shows your session as
   **manual**. Press **Generate review** on a short session (a few hundred lines; this spends NanoGPT
   tokens: about one call per 6,000 characters, plus one merge, plus one per 8 questions).
3. The review opens with "Generating: digest 1/N" and updates by itself. When done: read あらすじ,
   open English, check that 読み間違えやすい表現 quote real lines (**Find in Search** finds them).
4. Answer a quiz question in Japanese, Ctrl+Enter → 採点中… → verdict, score, corrections; open
   参考解答. Answer it again → 過去の解答 (1). Reload the page → the last grade is still there.
5. Failure path: GSM Settings → AI, break the key → Generate → the review fails with the provider
   message and a **Retry** button. Restore the key → **Retry** → it runs.
6. Auto-end: start a session, switch OBS to another game's scene → within 30 s the texthooker
   button is back to **▶ Session**. With the overlay running: start a session, close the game,
   wait over a minute → same.
7. Please write down: which highlights were genuinely useful, which were noise, and whether the
   number of questions felt right for the session length. That drives C.1/C.2.

---

## 2026-10-04 (owner present): friction first

Owner's test showed setup friction as the main problem: ten minutes of setup, a confusing
hook/OCR wizard, an overlay that never started, and lookups only in Firefox (alt-tab).
Decisions: one-click hub is the goal; hooked VNs get OCR on demand (hotkey), never
continuous OCR by default; hotkeys should avoid Ctrl/Shift/Alt (numpad proposed).

| What | Commit |
|---|---|
| Overlay never started: `GSM_Overlay/node_modules` was missing (installed); lockfile synced | `d30bca23` |
| Overlay output now in `logs/overlay.log`; exits and refused relaunches logged | `706c9fa4` |
| Dictionary import that died with the overlay is detected and retried | `2f91a02f` |
| Ask AI panel: overlay hotkey **Num0**, newest line, follow-ups; numpad hotkeys work in the overlay | `0218e863` |
| Looping title-screen text dropped (3rd copy within 60 s); setup page "Text source" row knows the built-in hook and warns about continuous OCR next to a hook | `c2fc52d5` |
| Review page: Lines / Delete lines / Remove mark per session | `331fc7b8` |
| Wizard: never switches to OCR by accident; hooked games get OCR on demand | `8ea7fb56` |
| Reading session and Anki start/stop with the active game (Home tab switches) | `b04d3b01` |
| Ask AI: custom questions may use general language knowledge (readings of names, grammar) | `7c3c1284` |
| Home tab **Play**: starts a set-up game (OBS scene + its saved hook/OCR/overlay; Steam games via Steam) | `c4f3bd79` |
| Numpad layout for GSM, OCR and overlay hotkeys (one-time migration); **Num8** starts/ends a reading session | `cf3b4147` |
| GSM settings window keeps numpad hotkeys (Qt "Num+3" ↔ `num3`) | `c8f6ae6c` |
| Overlay settings window opens on the first run only (existing installs switched off once) | `17a1d772` |
| Overlay numpad keys held only while the game or an overlay window is in front | `241f3d98` |
| Wizard asks "What kind of game is it?" first (VN / emulator / can't be hooked / not sure) | `5495ecb2` |
| Home tab "How GSM works": app vs game vs browser pages, keys, hook vs OCR, sessions | `b5d201e0` |
| Input server parses numpad keys ("route all hotkeys" mode); binary rebuilt | `0bf72cd7` |

Data: all lines deleted on request (210 lines, 3 games); backup first at
`%APPDATA%\GameSentenceMiner\backup\gsm_backup_20261004_151249.db`.
Overlay Yomitan: synced from the Firefox export (5 dictionaries, all 3 card formats identical).

### Owner test (VN, about 10 minutes)
1. Start GSM only. Home tab: "Open and close with active game", "Start and end a reading session
   with the game" and "Start Anki with the game" should be on.
2. Home tab → Active Game Capture card: select Nekopara's scene → **Run Capture Wizard**. First
   question: **Visual novel on PC**. Hook step: click the line that matches the dialogue → "Next: OCR
   for pictures and extra boxes". OCR step: "OCR on demand (recommended)" is preselected. Save.
3. Press **Play** (or start the game). Within a few seconds: Anki opens, the overlay appears (no
   settings window), the hook delivers text.
4. Hover a word with Shift in the game: Yomitan pops up. Press **Num0**: the Ask AI panel shows the
   current line; ask a question, then a follow-up. Esc closes it.
5. Read a while, close the game. `localhost:55000/review`: one **manual** session covering exactly
   that time. Lines shows them; Generate review works on it.
   Num8 in the game ends/starts a session by hand; a short message over the game confirms it.
   Alt-tab to a browser: the numpad types digits there (the overlay lets go of the keys).
6. `localhost:55000/setup-check`: "Text source" says the built-in hook, OCR on demand.

### Hotkeys (numpad, NumLock on) — `cf3b4147`
| Key | Action | Where |
|---|---|---|
| Num0 | Ask AI about the current line | overlay |
| Num1 | OCR the dialogue area once | GSM OCR |
| Num2 | OCR: draw a box | GSM OCR |
| Num3 | Replay the last voice line | GSM |
| Num4 | TextFeed | overlay |
| Num5 | Show/hide the overlay box | overlay |
| Num6 | Translate | overlay |
| Num7 | Furigana | overlay |
| Num8 | Reading session start/end (toast over the game) | overlay → GSM |
| Num9 | Pause text capture | GSM |
| Num/ | Overlay settings | overlay |
| Num* | Yomitan settings | overlay |
| Num- | Live stats | overlay |
| Num+ | spare | |

Migration runs once per app (`numpad_layout_applied`, `ocrNumpadHotkeysApplied`,
`numpadHotkeysApplied`) and only moves hotkeys still at an old default. The overlay migrates on
its next start. New route: `POST /api/review/sessions/toggle` (adds no table).
GSM settings window: Qt calls keypad 3 "Num+3"; the hotkey fields convert to and from `num3`, so
opening settings no longer saves numpad hotkeys as empty, and pressing a numpad key records it.

## 2026-10-05: D. Anime, manga and YouTube (GSM Connect)

A browser extension (`gsm_connect/`, Chrome/Edge/Firefox, no build step) sends what is read in the
browser to GSM; GSM files each line under its own title. See `gsm_connect/README.md`.

| What | Commit |
|---|---|
| GSM: `POST /api/connect/lines`, source kind `browser`, per-line title, no OBS media on browser cards, burst-safe, Ask AI titled by the newest line | `a586732e` |
| Extension + setup-check row + Home card mention | `4bd9f092` |

- **Reads:** asbplayer subtitles (any site and its own player; first track), YouTube captions,
  Manatan anime subtitles and manga text boxes, Netflix captions, `<video>` subtitle tracks, mokuro
  pages. Furigana is dropped; manga columns are joined into one line per bubble.
- **Titles:** YouTube video title; anime/manga series (episode/chapter numbers dropped), editable
  in the popup per video/episode.
- **Offline:** lines wait in the extension (up to 5000) and arrive with their original times.
- **Ask AI:** popup button or Alt+Shift+A opens GSM's Ask AI window with the newest line.
- **Checked:** unit tests (Python, extension) and an end-to-end run in headless Edge against a fake
  GSM (asbplayer lines, background-tab timing, manga pages, titles). Not yet tried on the real
  YouTube / asbplayer / Manatan sites.

### Review grading after the owner's first real review (2026-10-05)
Owner graded an Azumanga Daioh session (WhisperAI subtitles). Problems seen and fixed:
- The grader saw only the quoted line, so it invented feelings (自己嫌悪); it now gets 3 lines of
  context on each side.
- Transcription errors (聞いたね for 聞いてね) were silently "corrected" and the learner marked
  down; graders now say the line looks mis-transcribed and do not penalize; quizzes avoid such lines.
- ✎ fixes rewrote the answer's content; now only real wording problems in the learner's own words.
- A question inside an answer was ignored; it is now answered ("質問への回答").
- Score and verdict disagreed (不正解 vs partial); scores are kept inside the verdict's band.
- New 質問・異議 box per grade: the AI replies and may revise the grade (original kept).

### Owner test (GSM Connect, about 10 minutes)
1. Load `gsm_connect` as an extension (README: Chrome/Edge unpacked, or Firefox temporary add-on).
2. YouTube: a Japanese video with Japanese CC on. The popup says "Reading YouTube captions"; the
   badge counts down to nothing while GSM runs. GSM text log shows the lines.
3. Anime in asbplayer (or Manatan): popup title should be the series without the episode number.
4. Manga in Manatan: each bubble appears once in the text log as you turn pages.
5. Close GSM, watch a minute (badge counts up, amber), start GSM: the lines arrive.
6. `localhost:55000/review`: the video/series has its own sessions; Generate review works.
7. Mine a word with Yomitan on the video: GSM must not add a game screenshot or audio to it.

### Still open (next)
- Owner test of GSM Connect (steps above); Firefox permanent install needs one signing step (README).
- Owner test of today's changes (steps above).
- Trails in the Sky: the OCR-all-the-time path (wizard "can't be hooked").
- The 5-minute overlay relaunch block: check `logs/overlay.log` next time it happens.
- Then F if a second PC is near, D if anime/manga, else H (owner's earlier decision).
