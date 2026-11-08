# MLACC-UVM

A coverage-driven **UVM verification environment** for **MLACC**, a small ML accelerator IP:
the int8 dot-product / multiply-accumulate / requantize datapath of the
Vortex-V RISC-V core (`vortex_xmlacc.sv`, used byte-for-byte) wrapped with an
**APB3 register block**, **valid/ready command and result streams**, a 4-deep result FIFO with
credit-based flow control, and an interrupt.

The bench is written in **pyuvm** (IEEE 1800.2 UVM in Python) on **cocotb + Icarus Verilog**,
so it runs on free tools in CI. The architecture is standard UVM component for component;
protocol rules also exist as **SystemVerilog assertions** run under Verilator.

## Results

| | |
|---|---|
| Regression | 9 tests, 30 seeded runs, all passing (~15 s on 4 cores) |
| Functional coverage | **150/150 bins (100%)**, 21 coverpoints and crosses — [docs/COVERAGE.md](docs/COVERAGE.md) |
| Bug injection | **15/15 injected RTL bugs caught** — [docs/MUTATION.md](docs/MUTATION.md) |
| SVA | 6 assertions, 4 environment assumptions and 3 covers, bound into the DUT, run with Verilator `--assert` |
| Real bug found | **VTX-RQS-001** in Vortex-V's `rqs`, found by random stimulus on the very first run — [docs/KNOWN-ISSUES.md](docs/KNOWN-ISSUES.md) |

## Testbench architecture

```mermaid
flowchart LR
  subgraph test[mlacc_base_test and 8 tests]
    subgraph env[MlaccEnv]
      APB[ApbAgent<br/>sqr · drv · mon]
      CMD[CmdAgent<br/>sqr · drv · mon]
      RSP[RspAgent<br/>responder · mon]
      SIG[SignalMonitor]
      RAL[MlaccRegBlock<br/>map · adapter]
      PRED[MlaccRegPredictor]
      SB[MlaccScoreboard<br/>Vortex-V golden model]
      CM[MlaccCycleModel<br/>CSR · IRQ · flow ctrl]
      PC[ProtocolChecker]
      COV[MlaccCoverage]
    end
  end
  DUT[[mlacc_top + bound mlacc_sva]]
  APB <--> DUT
  CMD --> DUT
  DUT --> RSP
  DUT --> SIG
  RAL -. frontdoor .-> APB
  APB -- ap --> PRED --> RAL
  CMD -- ap --> SB
  RSP -- ap --> SB
  SIG -- ap --> CM & PC & COV
  CMD -- ap --> COV
  APB -- ap --> COV
```

- **Agents:** APB3 master (active), command stream master with random idle gaps (active),
  result stream slave with random stall bursts (reactive), plus a passive per-cycle signal monitor.
- **RAL:** `uvm_reg_block` with 9 registers / 15 fields (RO, RW, W1C, volatile), an APB adapter
  and an **explicit predictor** (pyuvm ships no predictor body, so it is implemented here).
- **Scoreboard:** in-order, tag-checked comparison against Vortex-V's independent numpy golden model.
- **Cycle model:** a cycle-accurate model of the register block, interrupt and flow control that
  checks every APB read, `PSLVERR`, `irq` and `cmd_ready` every cycle.
- **Coverage:** a small covergroup library (coverpoints, crosses, illegal bins) and a merge script.
- **Sequences:** constrained-random traffic with weighted `dist`-style constraints over operand
  classes, rqs shift ranges, rounding points and accumulator wrap; directed corner sequences;
  RAL reset / bit-bash / access sequences; a virtual sequence that runs CSR traffic concurrently with
  data traffic.

## Tests

| Test | Purpose |
|---|---|
| `smoke_test` | one of each op + 50 random |
| `reg_test` | reset values, walking-1/0 bit-bash, RO write-ignore, unmapped `PSLVERR`, W1C |
| `corner_test` | lane extremes, macc wrap, every rqs shift boundary and half-way point, illegal ops |
| `random_test` | 2000 balanced random commands, light backpressure |
| `stress_test` | 3000 back-to-back commands into 50% bursty backpressure |
| `irq_test` | each IRQ source with its enable on/off, W1C de-assertion |
| `csr_traffic_test` | register polling, W1C clears and enable toggling concurrent with traffic |
| `reset_midflight_test` | reset with a full FIFO, clean restart |
| `known_issue_vtx_rqs_001_test` | reproduces VTX-RQS-001 with the waiver off (expected fail) |

## Running

```bash
sudo apt-get install -y iverilog verilator
pip install -r requirements.txt

make -C sim TEST=test_mlacc UVM_TEST=random_test SEED=7     # one test
python3 sim/run_regression.py -j 4                           # full regression
python3 sim/coverage_report.py reports/raw/regression/cov    # merged coverage
python3 sim/mutants.py -j 4                                  # bug-injection campaign
sim/run_sva.sh 1                                             # SVA under Verilator
python3 -m pytest tb/unit                                    # reference-model unit tests
```

## Layout

```
rtl/   mlacc_top, mlacc_csr, mlacc_fifo, mlacc_pkg, vortex_xmlacc (+ vortex_pkg), mlacc_sva (bound SVA)
tb/    mlacc_tb/ (agents, RAL, scoreboard, cycle model, coverage, sequences), tests/, unit/
sva/   Verilator harness that executes the bound SVA
sim/   cocotb Makefile, regression runner, coverage merge, mutation campaign
docs/  DUT-SPEC, VPLAN (requirement → test → checker → coverage), COVERAGE, MUTATION, KNOWN-ISSUES
```

## Why pyuvm and not SystemVerilog UVM

No free simulator runs Accellera SV-UVM out of the box today (Verilator support is recent and
partial; Icarus has none). pyuvm keeps the same class hierarchy, phasing, TLM, sequencer/driver
handshake, ConfigDB, factory and register layer, so the structure maps one-to-one onto an SV-UVM
bench. An SV-UVM port is planned once a UVM-capable simulator is available.
