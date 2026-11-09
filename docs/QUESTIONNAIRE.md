# Questionnaire — decisions before the first Claude Code pass

Answer with your teammate. Every question has a default; if you don't answer, the default is what SPEC.md and CLAUDE.md already say. The ones marked ⚑ change what Claude Code builds; the others change how you work.

## A. Things that block the first pass

**Q1 ⚑ Repo location and hosting.**
Where does the code live and where is it pushed?
- Default: `~/Projects/chess-c/` (outside the vault, per your vault rules), private GitHub repo, made public or zipped on Nov 27.
- Your answer:

**Q2 ⚑ Toolchain on the Mac.**
Apple clang (comes with Xcode Command Line Tools) builds everything in pass 1, but it ships no libFuzzer, which pass 2 needs.
- Default: Apple clang now; `brew install llvm` when pass 2 starts (and write the install hurdle down, the guidelines explicitly welcome it).
- Alternative: Homebrew LLVM from day one so the Makefile never changes.
- Your answer:

**Q3 ⚑ Move representation.**
- Default: a plain struct (`from, to, promo, flags`). Readable, debuggable, and the packed 16-bit version becomes a measured optimisation in pass 3 instead of a day-one obscurity.
- Alternative: packed `uint16_t` from the start (what real engines do).
- Your answer:

**Q4 ⚑ En-passant square in FEN output.**
After a double pawn push, do we write the e.p. square in the FEN always, or only when a capture is actually possible (python-chess's default when it writes FENs)?
- Default: store it always, write it always. The differential test compares move lists, not FEN strings, so this only affects FEN round-trip tests.
- Your answer:

**Q5 Who writes what (the learning policy).** This is the most important one and only you can answer it.
You will present for 10 minutes and may be asked to explain any line.
- (a) Claude writes everything; you review each module and make Claude explain it; you rewrite nothing.
- (b) **Recommended.** You two write the core by hand: `movegen.c` and `make.c` (the chess rules). Claude writes the scaffolding (Makefile, CLI, FEN, test harness, differential tool, CI), reviews your code against the spec, and does the performance work in pass 3 with you.
- (c) Claude drafts everything, then each of you rewrites one module from scratch without looking (the in-class assignments are LLM-free, so this doubles as practice).
- Your answer:

**Q6 Timeline per pass.**
- Default: pass 1 done by Fri Nov 13, pass 2 by Fri Nov 20, pass 3 and freeze by Mon Nov 23, report Nov 24–27.
- Your answer:

## B. Things that shape how you work with Claude Code

**Q7 Continuous integration.**
A 15-line GitHub Actions workflow running `make test` on Ubuntu proves "builds on Linux too" (the ABI/portability lecture) for free.
- Default: yes, from pass 1.
- Your answer:

**Q8 Enforcement.**
Two deterministic rules Claude Code can enforce regardless of what the model decides:
- A `Stop` hook that runs `make test` and refuses to let Claude finish while it fails. Default: on, once the Makefile exists.
- A `deny` rule so Claude can never edit `tests/perft_suite.epd` (the reference numbers). Default: on.
- Your answer:

**Q9 Commits.**
- Default: Claude never commits; you commit, with your own messages, after reading the diff. (Reading diffs is how you'll be able to explain the code.)
- Alternative: Claude commits when `make test` is green, you review by PR.
- Your answer:

**Q10 Division of labour between the two of you.**
Two people, one repo: who owns which module, and do you each run your own Claude Code session on your own branch (worktrees keep them from colliding)?
- Default: branches per module, `main` protected, merge after `make test` is green on both machines.
- Your answer:

**Q11 Measurement platform (pass 3).**
- Default: timings on the Mac with `hyperfine`; hardware counters (cache misses, branch misses) on the course Linux VM with `perf stat`. Report both.
- Your answer:

**Q12 Language.**
- Default: code, comments, commit messages and HURDLES.md in English (the report is in English).
- Your answer:

## C. Pass 2–3 choices (answer later)

**Q13** Terminal UI: Unicode pieces with an `--ascii` flag; input accepted as UCI (`e2e4`) and SAN (`Nf3`)? Default: yes to both.
**Q14** Engine target: local `cutechess-cli` tournaments only, or also a Lichess bot account via `lichess-bot`? Default: local only; Lichess is a "could".
**Q15** Perft performance ladder: which rungs are mandatory for the report? Default: mailbox → bitboard attack detection → lookup tables → one of {magics, copy-make, threads}.

## D. Not a question, a reminder
The topic you submitted on Oct 30 was the photo → PGN project. The guidelines say a change must be approved by email. Send it before the first commit, in three sentences: what it is now, why the change, what stays (python-chess as test oracle, the photo path as an optional input).

## What to remove from the roadmap before Claude Code sees it
The roadmap doc in the project is for the two of you. Claude Code gets only CLAUDE.md and SPEC.md:
- Lecture-link table, week dates, assignment reminders, scores from the ideas board: humans only.
- The "could" list and pass 3 details: present in SPEC.md only as "later", with pass 1's "Not in this pass" stated explicitly, otherwise the agent builds bitboards on day one because it can.
- Team rules like "functions under 40 lines": kept, in CLAUDE.md, because Claude can't infer them from an empty repo.
