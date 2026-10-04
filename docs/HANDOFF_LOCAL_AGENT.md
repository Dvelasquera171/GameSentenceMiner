# Handoff: ecosystem work → local Claude Code agent

Branch: `claude/vigilant-meitner-q8xjt5` on `Dvelasquera171/GameSentenceMiner`, checked out at
`D:\Projects\GameSentenceMiner`. GSM runs from source there (`npm run start`).

Plan and order: [ECOSYSTEM.md](ECOSYSTEM.md). Session Review details: [SESSION_REVIEW.md](SESSION_REVIEW.md).
Owner's real configs: `snapshots/` in the `jp-mining-tools` repo.

## Working agreement

- Builder role. Architecture, contracts and order in ECOSYSTEM.md are decided; build on them.
  Before each item, say in a few lines what will change and which files, then proceed.
- Ask first before: a new or changed database table, a changed API shape (additive optional
  fields are fine), any write to Anki (fields, note types, notes), any change to Luna's config.
- Branch only, never `main`. One roadmap item per commit; push after each green step.
- Python: `uv run ruff format GameSentenceMiner tests scripts`
  (uv is `%APPDATA%\GameSentenceMiner\uv\uv.exe` if not on PATH), then
  `.\.venv\Scripts\python.exe -m pytest tests/ai tests/web tests/util/database tests/util/test_reading_sessions.py -q`.
  Report real output.
- Ready to try: `npm run agent:restart -- --reason "<what changed>"` (`--build` for Electron
  changes). Nonzero exit is a failure; never kill processes by name.
- Texthooker UI is Svelte in `texthooker/src`, rebuilt with `build_for_gsm.ps1`. Flask pages
  under `GameSentenceMiner/web` need no build. Overlay GSM-side files live in `GSM_Overlay/*.js`;
  never edit `GSM_Overlay/yomitan/`.
- No API keys in code, config files, tests, docs or commit messages. Ever.
- Every step ends with exact click-by-click test steps for the owner, who runs the games, Anki,
  OBS, Luna and Firefox. The agent cannot.

## Order of work

1. **E. Setup health page** (ECOSYSTEM.md §E). Endpoint + Flask page + tests. Owner tests it.
2. **Y. Yomitan sync from the Firefox export** (§Y). Start with the merge rules and their
   tests, then the overlay apply path, then the dictionary import, then the health-page row.
3. **Q. AI help follow-ups and context size** (§Q).
4. **Session Review A → B → C** (SESSION_REVIEW.md), using the owner's feedback from their
   first real `/review` run.
5. Stop and ask whether D (title override for anime/manga) or F (second-PC deploy script in
   jp-mining-tools) comes next.
