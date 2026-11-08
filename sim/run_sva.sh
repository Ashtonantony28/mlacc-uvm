#!/usr/bin/env bash
# Build and run the bound SVA under Verilator with random legal stimulus.
#   sim/run_sva.sh [SEED] [MUTANT]     -> exit 0 if no assertion fires
set -euo pipefail
cd "$(dirname "$0")/.."
SEED=${1:-1}; MUT=${2:-}
OBJ=sim/sva_build${MUT:+_$MUT}
DEF=${MUT:+-D$MUT}
verilator --binary --timing --assert --timescale 1ns/1ps $DEF -Wno-fatal -Wno-lint -Wno-style -Irtl rtl/lint.vlt \
  $(sed 's|^|rtl/|' rtl/files.f) rtl/mlacc_sva.sv sva/sva_tb.sv --top-module sva_tb \
  -Mdir "$OBJ" -j "$(nproc)" >/dev/null
"$OBJ/Vsva_tb" +seed="$SEED"
