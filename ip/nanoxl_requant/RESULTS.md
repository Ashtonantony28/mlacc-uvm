# NanoXL requant bench results

Regression: 13/13 runs pass (tests x seeds, NDSP 4 and 3).

Coverage: 22/22 bins hit.

Mutants: 11/11 killed.

| Bin | Hits |
| --- | --- |
| `mode_x_result.out8.in_range` | 7103 |
| `mode_x_result.out8.zero` | 4762 |
| `mode_x_result.out8.sat_hi` | 6245 |
| `mode_x_result.out8.sat_lo` | 6061 |
| `mode_x_result.out16.in_range` | 12135 |
| `mode_x_result.out16.zero` | 4547 |
| `mode_x_result.out16.sat_hi` | 3248 |
| `mode_x_result.out16.sat_lo` | 3174 |
| `shift.zero` | 7098 |
| `shift.mid` | 33295 |
| `shift.max` | 6882 |
| `round.tie` | 3802 |
| `bias.wrap` | 2699 |
| `srdhm.overflow` | 20 |
| `mult.min_legal` | 8390 |
| `mult.max` | 5548 |
| `flow.backpressure` | 32393 |
| `flow.back_to_back` | 7922 |
| `flow.partial_keep` | 2342 |
| `flow.last` | 1234 |
| `flow.clr_with_sat_event` | 310 |
| `flow.counter_clear` | 1400 |

## Mutation campaign

| Mutant | File | Bug | Killed by |
| --- | --- | --- | --- |
| `RDIVPOT_NO_SIGN` | requant.sv | rdivpot rounds negative ties toward zero (sign term dropped) | corner_test, random_test, stress_test |
| `BIAS_DROPPED` | requant.sv | bias never added | corner_test, random_test, stress_test |
| `CLAMP8_HI` | requant.sv | int8 positive saturation value off by one | corner_test, random_test, stress_test |
| `FIT16_SHORT` | requant.sv | int16 range check one bit too wide (32768 passes unclamped) | random_test, stress_test |
| `STALL_IGNORED` | requant.sv | pipeline advances while the output is stalled (beats lost) | corner_test, random_test, stress_test |
| `SAT_KEEP_UNMASKED` | requant.sv | out_sat reported for lanes with keep = 0 | random_test, stress_test |
| `LAST_LOST` | requant.sv | out_last never set | corner_test, random_test, stress_test |
| `SRDHM_NO_NUDGE` | srdhm.sv | SRDHM rounding nudge dropped | corner_test, random_test, stress_test |
| `SRDHM_NO_OVF` | srdhm.sv | SRDHM INT32_MIN x INT32_MIN overflow not saturated | corner_test |
| `CNT_CLR_DROPS_EVENT` | sat_counter.sv | a saturation event in the same cycle as sat_clr is lost | random_test, stress_test |
| `STICKY_NOT_STICKY` | sat_counter.sv | sat_sticky only pulses | corner_test, random_test, stress_test |
