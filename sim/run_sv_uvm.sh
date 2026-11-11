#!/usr/bin/env bash
# Build and run the SystemVerilog UVM bench with Verilator >= 5.054.
#   sim/run_sv_uvm.sh TEST [SEED]          e.g. sim/run_sv_uvm.sh random_test 7
# Env: MUTANT (optional MUTANT_* macro), VERILATOR (default: verilator on PATH), UVM_HOME (Accellera UVM src dir).
set -euo pipefail
cd "$(dirname "$0")/.."
TEST=${1:-smoke_test}; SEED=${2:-1}
VERILATOR=${VERILATOR:-verilator}
UVM_HOME=${UVM_HOME:?set UVM_HOME to the UVM library src/ directory}
OBJ=sim/sv_uvm_build${MUTANT:+_$MUTANT}
if [ ! -x "$OBJ/Vtb_top" ] || [ -n "${REBUILD:-}" ]; then
  "$VERILATOR" --binary --timing -j "$(nproc)" -Wno-fatal -Wno-lint -Wno-style \
    --error-limit 50 +define+UVM_NO_DPI ${MUTANT:+-D$MUTANT} +incdir+"$UVM_HOME" -Irtl -Isv_uvm \
    "$UVM_HOME/uvm_pkg.sv" $(sed 's|^|rtl/|' rtl/files.f) \
    sv_uvm/mlacc_if.sv sv_uvm/mlacc_uvm_pkg.sv sv_uvm/tb_top.sv \
    --top-module tb_top -Mdir "$OBJ"
fi
LOG="$OBJ/$TEST.s$SEED.log"
"$OBJ/Vtb_top" +UVM_TESTNAME="$TEST" +verilator+seed+"$SEED" | tee "$LOG"
grep -q '\*\*\* TEST PASSED \*\*\*' "$LOG"     # exit status = test result
