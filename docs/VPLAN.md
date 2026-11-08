# Verification plan (requirements → stimulus → checker → coverage)

| ID | Requirement (DUT spec) | Stimulus (test / sequence) | Checker | Coverage |
|---|---|---|---|---|
| D1 | `dot8/dot8u/dot8su/macc` results bit-exact vs Vortex-V golden model | all tests; `RandCmdSeq`, `corner_vectors` | `MlaccScoreboard` | `cg_cmd.op_x_rs1/rs2`, `macc_acc` |
| D2 | `rqs` round-half-up, ASR, clamp, SAT flag; rs2[63:6] ignored | `corner_test` (every shift / half-way point), random | scoreboard | `rqs_shift_x_outcome` |
| D3 | illegal ops return 0 and set IRQ_STATUS.ERR | random (2% weight), `irq_test`, `csr_traffic_test` | scoreboard + `MlaccCycleModel` | `cg_cmd.op[illegal]`, `irq_source[err]` |
| F1 | results return exactly once, in order, with their tag | all | scoreboard (in-order queue) | — |
| F2 | 2-cycle latency when unstalled | all | `ProtocolChecker` p_lat_*, SVA `p_lat_s1/p_lat_fifo` | — |
| F3 | credit flow control: never > 4 results buffered, `cmd_ready` exactly per spec | `stress_test`, `reset_midflight_test` | cycle model (`cmd_ready`, occupancy), SVA `p_credit/p_no_overflow` | `fifo_level`, `cmd_stall_reason` |
| F4 | `rsp_*` held stable while `rsp_ready=0` | `stress_test` (50% stall, bursts ≤ 8) | protocol checker, SVA `p_rsp_hold/p_rsp_stable` | `rsp_backpressure` |
| F5 | full throughput: back-to-back commands, simultaneous cmd+rsp | `smoke_test`, `stress_test` | scoreboard | `cmd_back_to_back`, `cmd_and_rsp_same_cycle` |
| F6 | CTRL.EN=0 blocks commands; in-flight results still drain | `csr_traffic_test` | cycle model | `cmd_stall_reason[disabled]`, `disable_while_busy` |
| R1 | reset values of every register | `reg_test` | RAL mirror + cycle model | `reg_x_dir` |
| R2 | RW registers hold every bit pattern | `reg_test` bit-bash (walking 1/0) | RAL mirror + cycle model | `reg_x_dir` |
| R3 | RO registers ignore writes, no error | `reg_test` (raw APB) | RAL mirror + cycle model | `reg_x_dir` |
| R4 | unmapped addresses: PSLVERR, read 0, full 12-bit decode | `reg_test` (`UNMAPPED_PROBES` up to 0xFFC) | cycle model | `reg[unmapped]` |
| R5 | W1C semantics; hardware set wins over same-cycle clear | `reg_test`, `csr_traffic_test` | cycle model | `w1c_set_collision` |
| R6 | CMD/RSP counters | `csr_traffic_test` | cycle model | — |
| I1 | `irq` = OR of (IRQ_STATUS & enables), every cycle | `irq_test`, `csr_traffic_test` | cycle model (every cycle) | `irq_source` |
| X1 | synchronous reset with traffic in flight | `reset_midflight_test` | all checkers re-arm on `ResetEvent` | `reset_with_traffic` |

Closure criteria: regression green over all seeds, 100% of defined coverage bins, every
mutant in `sim/mutants.py` killed. Results: [COVERAGE.md](COVERAGE.md), [MUTATION.md](MUTATION.md).
