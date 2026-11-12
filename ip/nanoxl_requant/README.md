# Second DUT: NanoXL requantizer

This applies the MLACC-UVM method (pyuvm agents, an in-order scoreboard against a
golden model, a per-cycle model, functional coverage and a mutation campaign) to a
second IP from a different project: `requant.sv` from
[nanoxl-accelerator](https://github.com/Ashtonantony28/nanoxl-accelerator), the
L-lane pipelined int32 → int8/int16 requantizer behind NanoXL's systolic array
(contract C2: gemmlowp `SRDHM` + `RoundingDivideByPOT` + clamp).

The RTL in `rtl/` is a byte-identical copy at the commit in `UPSTREAM.md`; the fast
tests fail if it drifts. Bugs are injected by patching a temporary copy, so nothing
in `rtl/` carries mutation hooks.

## What is checked

- **Golden model.** `ref.py` restates contract C2 in plain Python. It is pinned to
  NanoXL's numpy model by 6,000 committed cases (`fixtures/c2_cases.json`, made by
  `gen_fixture.py` from `nanoxl.numerics.requant`), including 278 exact rounding ties.
- **Scoreboard.** Every output beat (all 4 lanes, `out_keep`, `out_sat`, `out_last`)
  is matched in order with the input beat that produced it.
- **Cycle model.** `sat_count` and `sat_sticky` are predicted every cycle, including
  `sat_clr` landing in the same cycle as a saturation event.
- **Stimulus.** Random beats (extremes, ties, bias wraps, partial `keep`, int8/int16
  mix), directed corners (a tie at every shift, the `SRDHM(INT32_MIN, INT32_MIN)`
  overflow), random idle gaps, and output backpressure bursts up to 12 cycles.
- **Both multiplier builds.** Runs use `NDSP=4` and the 3-DSP fabric variant.

Results (2026-11-12, see `RESULTS.md`): 13/13 regression runs pass, 22/22 coverage
bins hit, 11/11 injected bugs caught.

## The int8 rules across projects

The bench also documents why a shared int8 library is not a drop-in: the projects
use different requantize rules on purpose.

| Project | Rule | Rounding |
| --- | --- | --- |
| Vortex-V `mlacc.rqs` | `(x + 2^(s-1)) >> s`, clamp | half up (toward +inf) |
| NeuroFlight | `(acc*M + 2^(S-1)) >> S`, clamp | half up, same as `rqs` |
| NanoXL C2 | `RDIVPOT(SRDHM(x, mult), shift)`, clamp | half away from zero, twice |

The final shift steps agree except on exact negative ties (-2.5 becomes -2 with `rqs`
and -3 with NanoXL's `RoundingDivideByPOT`), and NanoXL also rounds inside `SRDHM`.
So a NanoXL layer cannot run on Vortex-V's `rqs` bit-exact without a correction step.

## Run

```
python3 -m pytest -q ip/nanoxl_requant/test_ref.py      # no simulator
python3 ip/nanoxl_requant/run.py -j 4                   # regression + coverage + mutants
make -C ip/nanoxl_requant/sim UVM_TEST=random_test SEED=3
```
