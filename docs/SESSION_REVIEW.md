# Session Review: comprehension summary + quiz

Status: **foundation laid, UI and integrations open.** This document is the roadmap for
whoever picks this up next (a local coding agent included). Read it together with
`docs/AI_AGENT_MAP.md`.

## Why

The owner's biggest immersion risk is the *silent misreading*: a construction read
wrong in a way that still fits the scene (「落ちそうになった」 read as "looked like it
would fall" instead of "almost fell"). Nothing in the game flags it. The review exists to
catch those after a session, to confirm the plot and register were understood, and to
turn the check into Japanese output practice (quiz answered in Japanese, graded live).

## What exists (this branch)

| Layer | File | Notes |
|---|---|---|
| Schema | `GameSentenceMiner/util/database/session_review_tables.py` | `reading_sessions` (manual Start/End only), `session_reviews` (status, stage, summary_ja/en, `highlights` dict, `quiz` list), `session_quiz_attempts`. Registered in `db.py` `_DATABASE_TABLE_CLASSES`; schema is created on startup like every other table. |
| Sessions | `GameSentenceMiner/util/reading_sessions.py` | `split_into_sessions` (gap rule, reuses `stats.session_gap_seconds`), `apply_manual_sessions` (manual range wins), `list_sessions`, `get_session_lines`, `start_manual_session`, `end_manual_session`. Grouping key: `game_id`, else `game_name`. Nothing is stored for auto sessions. |
| AI | `GameSentenceMiner/ai/features/session_review.py` + `GameSentenceMiner/ai/prompts/session_review.py` | `SessionReviewGenerator`: chunk → digest ×N → merge → quiz (batched, 8 per call) → result; `grade_answer` for live grading. Strict JSON at every stage, one retry on unparseable output. Quiz length scales with characters read (`quiz_question_count`). |
| API + page | `GameSentenceMiner/web/session_review_api.py`, `templates/review.html`, `static/js/review.js` | Routes listed at the top of the API module. Generation runs in a daemon thread; the row's `status/stage/progress/error` is what the page polls. Page is a bare scaffold: Japanese shown, English in `<details>`. |
| Tests | `tests/ai/test_session_review.py`, `tests/util/test_reading_sessions.py`, `tests/web/test_session_review_api.py` | Fake AI; no network. |

`AIService.generate_raw_prompt` gained an optional `max_tokens` so long structured outputs
are not cut at the translation default (4096).

### Data contracts

`session_reviews.highlights`:
```json
{"items": [Highlight], "characters": [{"name","attitude_ja","attitude_en"}],
 "may_have_missed_ja": ["..."], "may_have_missed_en": ["..."]}
```
`Highlight`: `line_id, quote, construction, naive_reading_ja/en, correct_reading_ja/en,
why_it_matters_en, category, confidence`. Categories in `prompts.HIGHLIGHT_CATEGORIES`.

`session_reviews.quiz`: list of `QuizQuestion` dicts
(`id, kind, question_ja, hint_ja, reference_answer_ja/en, rubric_en[], source_line_ids[]`).
Kinds: `events | speaker_intent | meaning_in_context | register`.

`grade` response: `verdict (correct|partial|incorrect), score 0-100, feedback_ja, feedback_en,
japanese_fixes[{original, fixed, note_en}], model_answer_ja`.

## Roadmap

Each item is meant to be one small PR. Order matters only where stated.

### A. Finish the review page (next)
1. Replace the scaffold in `review.html`/`review.js` with proper layout using the existing
   dashboard CSS. Keep the rule: Japanese visible, English collapsed, including per-question
   feedback. Everything Japanese should be selectable text so Firefox Yomitan works on it.
2. Progress UI while `status == running` (stage + `n/m`), retry button on `failed`
   (`POST /api/review/generate` again with the same range).
3. Quiz UX: show attempts history (`/attempts`), per-question "show reference answer" after a
   grade, overall score. Grading is one AI call per answer; show a spinner.
4. Highlight cards: link `line_id` back to the texthooker line (the texthooker already has
   `getGSMEndpoint`; a deep link or a copy button is enough).
5. Navigation: add `/review` to `templates/components/navigation.html`.

### B. Session boundaries
1. Texthooker Start/End buttons calling `/api/review/sessions/start|end` (Svelte source in
   `texthooker/src`, rebuild with `build_for_gsm.ps1`). Show the open-session badge.
2. Auto-end hooks: call `reading_sessions.end_manual_session(game_key=...)` when the game
   closes or the OBS scene changes. Entry points: `obs/service.py`
   (`CurrentProgramSceneChanged` → `gsm_state.current_game`) and
   `util/platform/windows_window_monitor.py` (window gone). Keep it to one call each.
3. Optional: "merge with previous" / "split here" on the sessions table for auto sessions
   (client-side range edit; `generate` already accepts any `start_ts/end_ts`).

### C. Quality of the AI output (iterate with real sessions)
1. Run on a real VN session, read the highlights. If they are vocabulary rather than
   constructions, tighten `CHUNK_DIGEST_PROMPT` step 3. If the English summary drifts from the
   Japanese one, tell the merge prompt to translate, not re-summarize (it already says so).
2. Tune `DEFAULT_CHUNK_CHARS`, `QUIZ_CHARS_PER_QUESTION`, `MAX_HIGHLIGHTS` after a few runs.
3. Consider a final "consistency pass" that checks every quiz `source_line_ids` exists and
   drops questions whose source is missing.
4. Speaker names: `ReviewLine.speaker` is empty today. If the text source provides names
   (LunaTranslator can), thread them through `gametext.py` → `game_lines`; the prompts
   already print `speaker:` when present.

### D. Non-game sources (anime, manga)
The review is source-agnostic: anything that lands in `game_lines` can be reviewed. Gaps:
1. **Source title override.** Lines are named after the OBS scene / window. Add a manual
   "current title" that `gametext.py` uses for `game_name` when set (config field +
   texthooker input). This is what makes subtitle streams and manga OCR group into their
   own sessions.
2. **asbplayer**: verify whether its websocket integration can emit the current subtitle
   text outward. If not, a 50-line bridge (subtitle file + player position → websocket on a
   port GSM already listens to) is the fallback. Do not add anime-specific code to GSM.
3. **manatan / manga OCR**: check its output path (clipboard or websocket). GSM's clipboard
   source already works; the title override above does the grouping.

### E. Setup health page (independent small PR)
`/setup-check`: Luna websocket connected (text runtime health already in `/get_status`),
AnkiConnect reachable, note type has every field GSM is configured to write
(`modelFieldNames`), AI provider configured and a 1-token test call succeeds. One line per
check with the fix.

### Non-goals
- Not a replacement for the texthooker "AI help" panel (`/analyze-line`), which already
  covers per-line questions. The review is for the session as a whole.
- No Anki writes from the review for now. A later step may offer "add highlight as a card".

## Testing on the owner's PC

Prerequisites: GSM running from this branch, AI tab configured (OpenAI provider → NanoGPT),
at least one game with lines in the database.

1. Start GSM. In the log, confirm no error mentioning `reading_sessions`,
   `session_reviews` or `session_quiz_attempts` (tables are created at startup).
2. Open `http://localhost:55000/review` in Firefox (your texthooker port; default is 7275).
   The game dropdown lists games that have lines; the table lists sessions split by the
   stats "session gap" (default 30 min).
3. Click **Generate review** on a short session first (a few hundred lines). The review
   appears under "Reviews" as `running (digest 1/N)` and the card polls every 3 s. Expect
   roughly one AI call per 6000 characters plus one merge plus one call per 8 questions.
4. When `done`: read あらすじ, expand English, check 読み間違えやすい表現 cards quote real
   lines. Answer one quiz question in Japanese and click 採点; a grade with Japanese feedback
   and corrections to your Japanese should appear within a few seconds.
5. Manual sessions: click **Start session**, read for a while, click **End session**. The
   table shows that range with source `manual`, even across a long pause.
6. Failure path: set a wrong API key, click Generate; the review should end as `failed`
   with the provider's error in the status line, not hang.
7. Check NanoGPT usage after one review to decide whether the chunk size needs changing.

Report back: which highlights were genuinely useful, which were noise, and how many
questions felt right for the session length. Those three answers drive section C.
