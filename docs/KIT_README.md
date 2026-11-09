# chess-c — Claude Code kit

Drop these files into an empty repo (default `~/Projects/chess-c/`) before the first Claude Code session.

| File | Purpose |
|---|---|
| `CLAUDE.md` | Loaded every session. Commands, conventions, working rules. Keep it short. |
| `SPEC.md` | What to build, in passes, with a checkable definition of done. `[Q]` = open decision. |
| `FIRST_PROMPT.md` | The prompts for session 0 (interview), 1 (scaffolding), 2 (review of your movegen). |
| `docs/QUESTIONNAIRE.md` | 15 decisions with defaults. Answer A1–A6 before session 0. |
| `docs/CLAUDE_CODE_GUIDE.md` | How to prompt, check, enforce, steer, review (from the official best-practices page). |
| `tests/perft_suite.epd` | Six standard positions with reference node counts (verified against python-chess to depth 3–4). Never edit. |
| `tools/diff_vs_python_chess.py` | Differential test vs python-chess: `--games N`, `--divide FEN D`, `--fen FEN`. Tested: finds a planted en-passant bug in 3 games. |
| `.claude/settings.json` | Optional: Stop hook (`make test` must pass) + deny rule on the perft suite. Enable once the Makefile exists. |

Order of operations: answer the questionnaire → email the professor about the topic change → session 0 → `/clear` → session 1.
