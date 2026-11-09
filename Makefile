# Makefile — chess-c (pass 1)
#
# Targets:
#   make debug    -> build/debug/chess   (ASan + UBSan, -O0 -g, assertions on)
#   make release  -> build/release/chess (-O2, NDEBUG)
#   make test     -> unit tests + CLI exit-code checks + perft suite against the
#                    debug (sanitised) build; the differential test runs against
#                    the release build (sanitizer start-up made it 30x slower,
#                    see HURDLES.md 2026-11-07)
#   make clean    -> remove build/
#   make fuzz-fen / fuzz-pgn -> libFuzzer runs (Homebrew LLVM on macOS; see docs/FUZZING.md)
#
# Every .c under src/ is compiled; cli.c holds main() and is left out of the
# library objects that the unit tests link against.

# make's built-in default for CC is `cc`; prefer clang unless CC is given on the command line.
ifeq ($(origin CC),default)
CC := clang
endif
CFLAGS  := -std=c17 -Wall -Wextra -Werror -Wshadow -Isrc

# -fno-sanitize-recover=all: any UB report aborts the run instead of just
# printing, so `make test` cannot be green while UBSan is complaining.
DEBUG_CFLAGS   := -g -O0 -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer
RELEASE_CFLAGS := -O2 -DNDEBUG

SRCS     := $(wildcard src/*.c)
HDRS     := $(wildcard src/*.h)
LIB_SRCS := $(filter-out src/cli.c,$(SRCS))

DEBUG_OBJS       := $(patsubst src/%.c,build/debug/obj/%.o,$(SRCS))
RELEASE_OBJS     := $(patsubst src/%.c,build/release/obj/%.o,$(SRCS))
DEBUG_LIB_OBJS   := $(patsubst src/%.c,build/debug/obj/%.o,$(LIB_SRCS))

TEST_SRCS := $(wildcard tests/*.c)
TEST_BINS := $(patsubst tests/%.c,build/debug/tests/%,$(TEST_SRCS))

DEBUG_BIN   := ./build/debug/chess
RELEASE_BIN := ./build/release/chess
SUITE       := tests/perft_suite.epd

.PHONY: all debug release test clean fuzz-fen fuzz-pgn

all: debug release

debug: build/debug/chess
release: build/release/chess

build/debug/chess: $(DEBUG_OBJS)
	$(CC) $(CFLAGS) $(DEBUG_CFLAGS) $^ -o $@

build/release/chess: $(RELEASE_OBJS)
	$(CC) $(CFLAGS) $(RELEASE_CFLAGS) $^ -o $@

build/debug/obj/%.o: src/%.c $(HDRS)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(DEBUG_CFLAGS) -c $< -o $@

build/release/obj/%.o: src/%.c $(HDRS)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(RELEASE_CFLAGS) -c $< -o $@

build/debug/tests/%: tests/%.c $(DEBUG_LIB_OBJS) $(HDRS)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(DEBUG_CFLAGS) $< $(DEBUG_LIB_OBJS) -o $@

# expect_exit(command, code): run the command silently and require that exit code.
define expect_exit
	@$(1) >/dev/null 2>&1; rc=$$?; \
	if [ $$rc -ne $(2) ]; then echo "FAIL exit $$rc (expected $(2)): $(1)"; exit 1; \
	else echo "ok   exit $(2): $(1)"; fi
endef

test: debug release $(TEST_BINS)
	@echo "== unit tests (ASan + UBSan)"
	@set -e; for t in $(TEST_BINS); do echo "-- $$t"; $$t; done
	@echo "== CLI must reject bad input with exit 2 and never crash"
	$(call expect_exit,$(DEBUG_BIN),2)
	$(call expect_exit,$(DEBUG_BIN) frobnicate,2)
	$(call expect_exit,$(DEBUG_BIN) perft,2)
	$(call expect_exit,$(DEBUG_BIN) perft x,2)
	$(call expect_exit,$(DEBUG_BIN) perft -1,2)
	$(call expect_exit,$(DEBUG_BIN) perft 1 "garbage",2)
	$(call expect_exit,$(DEBUG_BIN) perft 1 "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0",2)
	$(call expect_exit,$(DEBUG_BIN) divide 1 "8/8/8/8/8/8/8/8 w - - 0 1",2)
	$(call expect_exit,$(DEBUG_BIN) moves "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq e3 0 1",2)
	$(call expect_exit,$(DEBUG_BIN) perft-suite tests/does_not_exist.epd 4,2)
	$(call expect_exit,$(DEBUG_BIN) perft-suite $(SUITE),2)
	$(call expect_exit,$(DEBUG_BIN) status "garbage",2)
	$(call expect_exit,$(DEBUG_BIN) pgn,2)
	$(call expect_exit,$(DEBUG_BIN) pgn tests/does_not_exist.pgn,2)
	$(call expect_exit,$(DEBUG_BIN) pgn Makefile,2)
	$(call expect_exit,$(DEBUG_BIN) pgn fuzz/corpus_pgn/scholars_mate.pgn,0)
	$(call expect_exit,$(DEBUG_BIN) play "garbage",2)
	@echo "== python-chess (oracle for tools/diff_vs_python_chess.py)"
	@if python3 -c "import chess" 2>/dev/null; then \
	  echo "ok   python-chess $$(python3 -c 'import chess; print(chess.__version__)')"; \
	else echo "SKIP python-chess not installed: run 'pip3 install --user chess'"; fi
	@echo "== perft suite (depth 4, ASan+UBSan) and differential test (50 games, release binary)"
	@$(DEBUG_BIN) moves >/dev/null 2>&1; rc=$$?; \
	if [ $$rc -eq 3 ]; then \
	  echo "SKIP move generation not implemented yet (session 2): perft-suite and diff test not run"; \
	else \
	  $(DEBUG_BIN) perft-suite $(SUITE) 4 && \
	  if python3 -c "import chess" 2>/dev/null; then python3 tools/diff_vs_python_chess.py --bin $(RELEASE_BIN) --games 50; \
	  else echo "SKIP diff_vs_python_chess.py: python-chess not installed"; fi; \
	fi
	@echo "== make test: all green"

clean:
	rm -rf build

# --- fuzzing (pass 2) -------------------------------------------------------
# Apple clang has no libFuzzer: use Homebrew LLVM (brew install llvm). On Linux
# `make fuzz-fen LLVM=/usr` works with the distribution's clang.
LLVM         ?= /opt/homebrew/opt/llvm
FUZZ_CC      := $(LLVM)/bin/clang
FUZZ_CFLAGS  := $(CFLAGS) -g -O1 -fsanitize=fuzzer,address,undefined -fno-sanitize-recover=all
FUZZ_SECONDS ?= 3600

build/fuzz/fuzz_%: fuzz/fuzz_%.c $(LIB_SRCS) $(HDRS)
	@test -x $(FUZZ_CC) || { echo "no clang at $(FUZZ_CC): brew install llvm (see docs/FUZZING.md)"; exit 2; }
	@mkdir -p $(dir $@)
	$(FUZZ_CC) $(FUZZ_CFLAGS) $< $(LIB_SRCS) -o $@

# libFuzzer writes the inputs it discovers into the FIRST corpus directory, so
# that one lives under build/ and the committed seed corpus in fuzz/ stays small.
fuzz-fen: build/fuzz/fuzz_fen
	@mkdir -p build/fuzz/corpus_fen
	$< -max_total_time=$(FUZZ_SECONDS) -max_len=256 build/fuzz/corpus_fen fuzz/corpus_fen

fuzz-pgn: build/fuzz/fuzz_pgn
	@mkdir -p build/fuzz/corpus_pgn
	$< -max_total_time=$(FUZZ_SECONDS) -max_len=4096 build/fuzz/corpus_pgn fuzz/corpus_pgn
