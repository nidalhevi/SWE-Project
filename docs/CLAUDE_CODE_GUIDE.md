# Working with Claude Code on chess-c

Distilled from the official best-practices page (code.claude.com/docs/en/best-practices, read Nov 2026) and applied to this project. The page's own summary: *tell Claude what it can't see, give it a check to run, and enforce the rules that can't have exceptions.*

## 1. Session zero: turn the roadmap into a spec by interview
The docs recommend exactly this for a project you haven't fully pinned down:

```
I want to build a chess rules engine in C for a course project. Read SPEC.md and CLAUDE.md.
Interview me until you could resolve every [Q] item and anything else you'd need before
writing code, then rewrite SPEC.md with the answers. Multiple-choice questions where possible.
```

Then `/clear` and start the build in a fresh session, so it begins from the written spec, not from the interview.

## 2. Keep CLAUDE.md short and specific
- Under ~60 lines here (the docs say under 200). Only what Claude can't read from the repo: the commands that verify work, decisions you made, things you've had to correct twice.
- Don't describe the architecture in it; Claude reads the code. The architecture lives in SPEC.md, which Claude reads when told.
- Run `/context` once to confirm it loaded; `/doctor` later to trim it.
- Personal preferences (your editor, your shell) go in `CLAUDE.local.md`, gitignored.

## 3. Give it a check to run, every time
The single most valuable line in CLAUDE.md is `make test`. Pattern for every task:

```
implement fen_parse() per SPEC.md §Data model. write tests/test_fen.c first with the 20 malformed
inputs, run `make test`, and keep going until it's green under the sanitizers. show me the test output.
```

Always ask for the evidence (the command and its output). "Tests pass" alone is not evidence.

Enforce it when it matters (`.claude/settings.json`):
```json
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "make test 1>&2 || exit 2" }] }]
  },
  "permissions": {
    "deny": ["Edit(./tests/perft_suite.epd)", "Write(./tests/perft_suite.epd)"]
  }
}
```
The hook sends Claude back to work while tests fail; the deny rule makes the reference numbers untouchable regardless of what the model decides. The docs' rule of thumb: a line you keep re-emphasising in CLAUDE.md belongs in a hook; a hook for a mere preference should be deleted.

## 4. Prompts that work here
- Name the file, the symptom, and what "done" looks like: *"perft(4) on suite line 3 gives 43,210, expected 43,238. use `divide 4` against `python3 tools/diff_vs_python_chess.py --divide <fen> 4` to find the root move that differs, then descend. fix it, add the position to tests/test_movegen.c, show me the diff."*
- Hand over files with `@src/movegen.c` instead of describing them; paste compiler output rather than paraphrasing it.
- Say *be ambitious* when you want the full version (all malformed-FEN cases, not three). Say *skip style* when you ask for a review.
- `ultrathink` in one prompt for a hard bug; `/effort high` for a session of bug hunting; default effort for scaffolding.
- Words like "think step by step" or "don't be lazy" are ordinary text now; effort and a check to run are the real controls.

## 5. Review by someone who didn't write it
- `/code-review` reviews the diff in a fresh subagent that never saw the conversation.
- Against the spec: *"use a subagent to review src/movegen.c against SPEC.md §Rules that must be exact; report only gaps that affect correctness, skip style."*
- Or a second session: one of you reviews `@src/make.c` in a fresh session and pastes the findings to the other. Cheap and independent.
- A `.claude/agents/reviewer.md` with `tools: Read, Grep, Glob` is a reviewer that cannot edit, enforced by the harness.

## 6. Steering
- Watch the first minute. `Esc` stops Claude mid-action and keeps the work so far.
- `/rewind` (or `Esc` twice on an empty prompt) rolls code and/or conversation back to an earlier prompt: try the bold approach, rewind if it fails.
- After two failed corrections, `/clear` and write one better prompt that folds in what you learned; a third correction mostly re-reads two failures.
- `/clear` between unrelated tasks; `/compact keep the perft results and the Makefile targets` on a long session.
- `/btw` for a side question that shouldn't enter the history (e.g. "what does `-fsanitize=undefined` catch?").
- `/rename chess-pass1` so `claude --resume chess-pass1` picks the session up tomorrow.

## 7. Two people, one repo
- Each of you runs your own session on your own branch; `claude -w <branch>` starts a session in a git worktree so edits never collide.
- `main` protected; merge only after `make test` is green on both Macs and on CI.
- Claude doesn't commit (CLAUDE.md says so). Reading your own diffs is how you'll be able to explain the code in the presentation.

## 8. The learning loop (this is a course, not a product)
After every module Claude writes, ask:
```
explain src/make.c to me as if I had to reimplement it tomorrow without you: the data flow,
the one invariant that make/unmake must preserve, and the two most likely bugs. then quiz me with 3 questions.
```
And for the modules you write yourselves, flip it: you write, Claude reviews against SPEC.md and runs the suite.

## 9. Unattended runs (only once the suite exists)
Before leaving a long task running: does it know what done looks like (SPEC.md definition of done), can it check itself (`make test`), what can it touch (the deny rule, one branch), what stops it (`--max-turns`), who signs off (you, reading the diff). `/goal make test passes and perft-suite depth 5 passes in release` keeps a background run honest.

## 10. First prompt for the build session
See FIRST_PROMPT.md.
