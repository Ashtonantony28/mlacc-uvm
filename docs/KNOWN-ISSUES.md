# Known issues found by this environment

## VTX-RQS-001 — `mlacc.rqs` rounding add wraps at 64 bits (Vortex-V RTL vs golden model) — FIXED

- **Found:** 2026-11-08, first run of `smoke_test` (random `rqs` operand), then reproduced
  by the directed `known_issue_vtx_rqs_001_test`.
- **Where:** `rtl/vortex_xmlacc.sv` (copied unchanged from Vortex-V `rtl/core/`).
- **What:** the spec says `t = (rs1 + 2^(sh-1)) >>s sh`. The RTL computes the add in a
  64-bit signed vector, so when `rs1 + 2^(sh-1) > INT64_MAX` the sum wraps negative and the
  result clamps to **-128** (or gives -1 for `sh = 63`). The Vortex-V numpy golden model
  (`model/xmlacc_model.py`) adds in unbounded precision and returns **+127** / **1**.
- **Example:** `rs1 = 0x7FFF_FFFF_FFFF_FFFF, sh = 1` → RTL `0xFFFF_FFFF_FFFF_FF80` (-128),
  model `0x7F` (127), SAT=1 in both.
- **Reach:** only inputs within `2^(sh-1)` of INT64_MAX. Real requantize inputs are int32
  accumulators, so a quantized network never hits it, but it is a spec disagreement and
  Vortex-V's own 392-test suite did not catch it.
- **Suggested fix (Vortex-V):** do the add in 65 bits:
  `logic signed [XLEN:0] sum = {x_s[XLEN-1], x_s} + rnd; t = sum >>> sh;`
  or amend XMLACC-SPEC to state 64-bit wrapping and change the model.
- **Fixed:** 2026-11-11 in Vortex-V PR #2 (round-add and shift now in XLEN+1 bits). `rtl/vortex_xmlacc.sv`
  was re-synced from Vortex-V `main`; the waiver is off by default and `rqs_overflow_test` (pyuvm)
  plus the SV-UVM scoreboard now pass on these inputs.
- **Status before the fix:** waived in the scoreboard (`scoreboard.known_issue`), counted and
  reported as a warning on every run; `known_issue_vtx_rqs_001_test` runs with the waiver off
  and is marked expected-fail, so a fix shows up as an unexpected pass.
