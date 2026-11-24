#!/bin/sh
# bench_perft.sh — time the perft variants of the current release build with hyperfine (docs/perf.md).
# Usage: make release && tools/bench_perft.sh [threads]      (needs: brew install hyperfine)
set -e
BIN=./build/release/chess
THREADS=${1:-8}
KIWI="r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
hyperfine -N --warmup 1 --runs 5 \
  -n "start d6 make/unmake"        "$BIN perft 6" \
  -n "start d6 copy-make"          "$BIN perft-copy 6" \
  -n "start d6 $THREADS threads"   "$BIN perft-mt $THREADS 6" \
  -n "kiwipete d5 make/unmake"     "$BIN perft 5 \"$KIWI\"" \
  -n "kiwipete d5 copy-make"       "$BIN perft-copy 5 \"$KIWI\"" \
  -n "kiwipete d5 $THREADS threads" "$BIN perft-mt $THREADS 5 \"$KIWI\""
