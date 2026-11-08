#!/usr/bin/env python3
"""Regression runner: runs UVM tests over seeds in parallel, merges coverage.

  python3 sim/run_regression.py                 # default regression (see REGRESSION)
  python3 sim/run_regression.py --quick         # one seed per test (CI)
  python3 sim/run_regression.py --mutant MUTANT_X --tests smoke_test,reg_test
Exit status is non-zero if any test fails (expected-fail tests count as pass when they fail).
"""
import argparse
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

SIM = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SIM)

# test -> number of seeds in the full regression
REGRESSION = {
    "smoke_test": 2, "reg_test": 1, "corner_test": 2, "irq_test": 1,
    "random_test": 10, "stress_test": 4, "csr_traffic_test": 6, "reset_midflight_test": 3,
    "known_issue_vtx_rqs_001_test": 1,
}


def build(mutant=None):
    args = ["make", "-s", "-C", SIM, "TEST=test_mlacc", "UVM_TEST=__build_only__"]
    if mutant:
        args.append(f"MUTANT={mutant}")
    env = dict(os.environ, COCOTB_TEST_FILTER="__none__")
    subprocess.run(args, env=env, capture_output=True)


def run_one(test, seed, mutant, out_dir, timeout):
    tag = f"{test}.s{seed}" + (f".{mutant}" if mutant else "")
    results = os.path.join(out_dir, "xml", f"{tag}.xml")
    log = os.path.join(out_dir, "logs", f"{tag}.log")
    env = dict(os.environ, COCOTB_RESULTS_FILE=results, COV_DIR=os.path.join(out_dir, "cov"),
               COV_NAME=tag)
    args = ["make", "-s", "-C", SIM, "TEST=test_mlacc", f"UVM_TEST={test}", f"SEED={seed}"]
    if mutant:
        args.append(f"MUTANT={mutant}")
    t0 = time.time()
    try:
        p = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") + "\nTIMEOUT"
    with open(log, "w") as fh:
        fh.write(out)
    passed = False
    if os.path.exists(results):
        root = ET.parse(results).getroot()
        cases = root.findall(".//testcase")
        passed = bool(cases) and not any(c.find("failure") is not None or c.find("error") is not None
                                         for c in cases)
    first = next((ln.strip() for ln in out.splitlines() if "first:" in ln or "AssertionError" in ln), "")
    return dict(test=test, seed=seed, mutant=mutant, passed=passed, secs=time.time() - t0,
                log=log, first_error=first[:300])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--tests")
    ap.add_argument("--seeds", type=int)
    ap.add_argument("--mutant")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "raw", "regression"))
    ap.add_argument("-j", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    plan = dict(REGRESSION)
    if a.tests:
        plan = {t: plan.get(t, 1) for t in a.tests.split(",")}
    if a.quick:
        plan = {t: 1 for t in plan}
    if a.seeds:
        plan = {t: a.seeds for t in plan}
    for sub in ("xml", "logs", "cov"):
        os.makedirs(os.path.join(a.out, sub), exist_ok=True)

    build(a.mutant)
    jobs = [(t, 1000 + i, a.mutant) for t, n in plan.items() for i in range(n)]
    with ThreadPoolExecutor(a.j) as ex:
        res = list(ex.map(lambda j: run_one(*j, a.out, a.timeout), jobs))

    fails = [r for r in res if not r["passed"]]
    for r in res:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['test']:32s} seed={r['seed']}  "
              f"{r['secs']:6.1f}s  {r['first_error'] if not r['passed'] else ''}")
    print(f"\n{len(res) - len(fails)}/{len(res)} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
