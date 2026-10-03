# Handoff: session review feature → local Claude Code agent

Branch: `claude/vigilant-meitner-q8xjt5` on `Dvelasquera171/GameSentenceMiner`.
Design, contracts, roadmap and PC test steps: [SESSION_REVIEW.md](SESSION_REVIEW.md).

## Owner: one-time setup on the PC

```powershell
cd <your GSM clone>
git fetch origin claude/vigilant-meitner-q8xjt5
git checkout claude/vigilant-meitner-q8xjt5
uv --version                      # must be 0.12.4 (pyproject pins it); else: uv self update 0.12.4
uv sync --frozen --extra dev      # repo .venv for tests/ruff (the app uses its own managed Python)
.\.venv\Scripts\python.exe -m pytest tests/ai/test_session_review.py tests/util/test_reading_sessions.py tests/web/test_session_review_api.py -q
npm install
npm run start                     # Electron spawns the backend from this checkout
```

Then open `http://localhost:55000/review` in Firefox (your texthooker port) and run the
"Testing on the owner's PC" steps in SESSION_REVIEW.md once, before handing the agent the
prompt below. Your three answers from that run (useful highlights, noise, question count)
go into the prompt where marked.

## Working agreement for the local agent

- Builder role. The architecture and contracts in SESSION_REVIEW.md are decided; build on
  them, do not redesign. Ask before changing a table, an API shape, or anything in Anki.
- Work on this branch (or short-lived branches off it), never `main`. One roadmap item per
  commit/PR-sized change. Push after each green step.
- After Python changes: `uv run ruff format GameSentenceMiner tests scripts`, then the three
  review test files plus `tests/ai`, `tests/web`, `tests/util/database`.
- After changes the owner should try: `npm run agent:restart -- --reason "..."`
  (`--build` for Electron changes). Nonzero exit = failure; do not kill processes by name.
- Never write API keys into code, config, tests or docs. The NanoGPT key lives only in
  GSM's AI settings on the PC.
- Texthooker UI lives in `texthooker/src` (Svelte); rebuild with `build_for_gsm.ps1`.
  Flask pages (`web/templates`, `web/static`) need no build.
- Do not edit `GSM_Overlay/yomitan/`.
- Every change ends with exact manual test steps for the owner (they run the games, Anki,
  OBS; the agent cannot).
