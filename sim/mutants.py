#!/usr/bin/env python3
"""Mutation (bug-injection) campaign.

Each MUTANT_* macro in rtl/ injects one realistic design bug. For every mutant
this script rebuilds the DUT with the macro defined, runs every test once, and
records which tests fail ("kill" the mutant). A mutant no test kills is a hole
in the verification environment. Writes docs/MUTATION.md.

  python3 sim/mutants.py [-j 4] [--md docs/MUTATION.md]
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_regression import run_one, ROOT  # noqa: E402

MUTANTS = {
    "MUTANT_W1C_AS_RW":         ("CSR", "MLSTAT.SAT behaves as plain RW instead of W1C"),
    "MUTANT_DONE_LOST":         ("CSR", "IRQ_STATUS.DONE: a W1C in the same cycle as a new result wins (event lost)"),
    "MUTANT_RSP_COUNT":         ("CSR", "RSP_COUNT saturates at 7"),
    "MUTANT_IRQ_MASK":          ("CSR", "irq ignores the CTRL.IRQ_EN_* enables"),
    "MUTANT_SCRATCH_BIT":       ("CSR", "SCRATCH bit 15 stuck at 0"),
    "MUTANT_ADDR_ALIAS":        ("CSR", "APB decodes only PADDR[7:0]; 0x100 aliases ID, no PSLVERR"),
    "MUTANT_STATUS_LEVEL":      ("CSR", "STATUS.FIFO_LEVEL reported at bits [6:3] instead of [7:4]"),
    "MUTANT_CREDIT_OFF_BY_ONE": ("Flow", "cmd_ready credit check uses <= : FIFO can overflow"),
    "MUTANT_RSP_NO_HOLD":       ("Flow", "FIFO pops whether or not rsp_ready is high"),
    "MUTANT_TAG_SWAP":          ("Flow", "tag LSB flipped for macc/rqs results"),
    "MUTANT_ILLEGAL_OP":        ("Datapath", "illegal op codes return the dot8 result instead of 0"),
    "MUTANT_SAT_STUCK":         ("Datapath", "rqs SAT flag never reported"),
    "MUTANT_DOT8SU_AS_U":       ("Datapath", "dot8su decoded as dot8u (sign of rs1 lanes lost)"),
    "MUTANT_RQS_SHIFT_5BIT":    ("Datapath", "rqs shift amount bit 5 dropped (shifts >= 32 wrong)"),
    "MUTANT_MACC_ACC32":        ("Datapath", "macc accumulator truncated to 32 bits"),
}
TESTS = ["smoke_test", "reg_test", "corner_test", "irq_test", "random_test", "stress_test",
         "csr_traffic_test", "reset_midflight_test", "rqs_overflow_test"]


def campaign(mutant, out):
    return mutant, [run_one(t, 1000, mutant, out, 900) for t in TESTS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--md", default=os.path.join(ROOT, "docs", "MUTATION.md"))
    ap.add_argument("--only")
    a = ap.parse_args()
    out = os.path.join(ROOT, "reports", "raw", "mutation")
    for sub in ("xml", "logs", "cov"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    muts = a.only.split(",") if a.only else list(MUTANTS)
    jobs = [None] + muts                      # None = unmutated baseline
    with ThreadPoolExecutor(a.j) as ex:
        results = dict(ex.map(lambda m: campaign(m, out), jobs))

    base = results.pop(None)
    base_ok = all(r["passed"] for r in base)
    rows, survivors = [], []
    for m in muts:
        killers = [r for r in results[m] if not r["passed"]]
        if not killers:
            survivors.append(m)
        first = killers[0]["first_error"].replace("|", "\\|") if killers else ""
        first = first.split("AssertionError: ")[-1].replace("uvm_test_top.env.", "")[:170]
        rows.append(f"| `{m}` | {MUTANTS[m][0]} | {MUTANTS[m][1]} | "
                    f"{', '.join(k['test'] for k in killers) or '**SURVIVED**'} | {first} |")
    killed = len(muts) - len(survivors)
    md = ["# Mutation (bug-injection) campaign\n",
          f"Baseline (no mutant): {'all tests pass' if base_ok else 'FAILING'}. "
          f"**{killed}/{len(muts)} mutants killed** "
          f"(mutation score {100.0 * killed / len(muts):.0f}%). Each mutant is one `ifdef` in `rtl/`; "
          "run with `python3 sim/mutants.py`.\n",
          "| Mutant | Area | Injected bug | Killed by | First failure reported |",
          "|---|---|---|---|---|"] + rows
    text = "\n".join(md) + "\n"
    print(text)
    if not a.only:
        with open(a.md, "w") as fh:
            fh.write(text)
    sys.exit(0 if base_ok and not survivors else 1)


if __name__ == "__main__":
    main()
