#!/usr/bin/env python3
"""Regression, coverage merge and mutation campaign for the NanoXL requant bench.

  python3 ip/nanoxl_requant/run.py                 # regression + coverage + mutants
  python3 ip/nanoxl_requant/run.py --no-mutants    # regression + coverage only
Writes ip/nanoxl_requant/RESULTS.md. Exit status is non-zero on any failure, any
coverage hole, or any surviving mutant.

Mutants are applied as exact text patches to a copy of the vendored RTL (the copies
in rtl/ stay byte-identical with NanoXL), one realistic bug each.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tb"))

# (test, seed, NDSP)
REGRESSION = ([("smoke_test", 1, 4), ("corner_test", 1, 4), ("corner_test", 2, 3)]
              + [("random_test", s, 4) for s in range(1, 6)] + [("random_test", 6, 3)]
              + [("stress_test", s, 4) for s in range(1, 4)] + [("stress_test", 4, 3)])
MUTANT_TESTS = [("corner_test", 1000, 4), ("random_test", 1000, 4), ("stress_test", 1000, 4)]

MUTANTS = {
    "RDIVPOT_NO_SIGN": ("requant.sv", "thr  = (mask >> 1) + {31'd0, x[31]};", "thr  = (mask >> 1);",
                        "rdivpot rounds negative ties toward zero (sign term dropped)"),
    "BIAS_DROPPED": ("requant.sv", "x1  <= in_acc[i*32 +: 32] + in_bias[i*32 +: 32];",
                     "x1  <= in_acc[i*32 +: 32];", "bias never added"),
    "CLAMP8_HI": ("requant.sv", "(y5[31] ? -16'sd128 : 16'sd127)", "(y5[31] ? -16'sd128 : 16'sd126)",
                  "int8 positive saturation value off by one"),
    "FIT16_SHORT": ("requant.sv", "(y5[31:15] == {17{y5[31]}})", "(y5[31:16] == {16{y5[31]}})",
                    "int16 range check one bit too wide (32768 passes unclamped)"),
    "STALL_IGNORED": ("requant.sv", "assign adv       = !v[D-1] || out_ready;", "assign adv       = 1'b1;",
                      "pipeline advances while the output is stalled (beats lost)"),
    "SAT_KEEP_UNMASKED": ("requant.sv", "assign out_sat[i] = s6 & keep_p[D-1][i];", "assign out_sat[i] = s6;",
                          "out_sat reported for lanes with keep = 0"),
    "LAST_LOST": ("requant.sv", "last_p <= {last_p[D-2:0], in_last};", "last_p <= {last_p[D-2:0], 1'b0};",
                  "out_last never set"),
    "SRDHM_NO_NUDGE": ("srdhm.sv", "assign q = p2[63:30] + 34'd1;", "assign q = p2[63:30];",
                       "SRDHM rounding nudge dropped"),
    "SRDHM_NO_OVF": ("srdhm.sv", "y    <= ovf2 ? 32'sh7FFF_FFFF : $signed(q[32:1]);",
                     "y    <= $signed(q[32:1]);", "SRDHM INT32_MIN x INT32_MIN overflow not saturated"),
    "CNT_CLR_DROPS_EVENT": ("sat_counter.sv", "+ {{(W+1-PW){1'b0}}, pc};",
                            "+ (clr ? {(W+1){1'b0}} : {{(W+1-PW){1'b0}}, pc});",
                            "a saturation event in the same cycle as sat_clr is lost"),
    "STICKY_NOT_STICKY": ("sat_counter.sv", "sticky <= (clr ? 1'b0 : sticky) | (pc != '0);",
                          "sticky <= (pc != '0);", "sat_sticky only pulses"),
}


def patched_rtl(mutant, root):
    d = Path(root) / "rtl"
    shutil.copytree(HERE / "rtl", d)
    if mutant:
        f, old, new, _ = MUTANTS[mutant]
        text = (d / f).read_text()
        assert text.count(old) == 1, f"{mutant}: patch target not unique in {f}"
        (d / f).write_text(text.replace(old, new))
    return d


def run_one(test, seed, ndsp, mutant=None, cov_dir=None):
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        rtl = patched_rtl(mutant, tmp)
        results = Path(tmp) / "results.xml"
        env = dict(os.environ, COCOTB_RESULTS_FILE=str(results))
        if cov_dir:
            env["RQ_COV"] = str(Path(cov_dir) / f"{test}.s{seed}.n{ndsp}.json")
        p = subprocess.run(["make", "-s", "-C", str(HERE / "sim"), f"UVM_TEST={test}", f"SEED={seed}",
                            f"NDSP={ndsp}", f"RTL_DIR={rtl}", f"SIM_BUILD={tmp}/build"],
                           env=env, capture_output=True, text=True, timeout=900)
        ok = False
        if results.exists():
            cases = ET.parse(results).getroot().findall(".//testcase")
            ok = bool(cases) and all(c.find("failure") is None and c.find("error") is None for c in cases)
        out = p.stdout + p.stderr
        first = next((ln.strip() for ln in out.splitlines() if "AssertionError" in ln), "")
        return {"test": test, "seed": seed, "ndsp": ndsp, "mutant": mutant, "ok": ok, "first": first[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mutants", action="store_true")
    ap.add_argument("-j", type=int, default=os.cpu_count() or 2)
    a = ap.parse_args()
    from rq_tb import BINS
    cov_dir = Path(tempfile.mkdtemp())
    with ThreadPoolExecutor(a.j) as ex:
        reg = list(ex.map(lambda t: run_one(*t, cov_dir=cov_dir), REGRESSION))
    hits = {b: 0 for b in BINS}
    for f in cov_dir.glob("*.json"):
        for k, v in json.loads(f.read_text()).items():
            hits[k] += v
    holes = [b for b, v in hits.items() if v == 0]
    md = ["# NanoXL requant bench results\n",
          f"Regression: {sum(r['ok'] for r in reg)}/{len(reg)} runs pass "
          "(tests x seeds, NDSP 4 and 3).\n",
          f"Coverage: {len(BINS) - len(holes)}/{len(BINS)} bins hit.\n",
          "| Bin | Hits |", "| --- | --- |"] + [f"| `{b}` | {v} |" for b, v in hits.items()]
    survivors = []
    if not a.no_mutants:
        jobs = [(m, t) for m in MUTANTS for t in MUTANT_TESTS]
        with ThreadPoolExecutor(a.j) as ex:
            res = list(ex.map(lambda mt: run_one(*mt[1], mutant=mt[0]), jobs))
        md += ["", "## Mutation campaign\n", "| Mutant | File | Bug | Killed by |", "| --- | --- | --- | --- |"]
        for m, (f, _, _, desc) in MUTANTS.items():
            killers = [r["test"] for r in res if r["mutant"] == m and not r["ok"]]
            if not killers:
                survivors.append(m)
            md.append(f"| `{m}` | {f} | {desc} | {', '.join(killers) or '**SURVIVED**'} |")
        md.insert(3, f"Mutants: {len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed.\n")
    (HERE / "RESULTS.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:5]))
    for r in reg:
        if not r["ok"]:
            print("FAIL", r)
    if not all(r["ok"] for r in reg) or holes or survivors:
        print("holes:", holes, "survivors:", survivors)
        sys.exit(1)


if __name__ == "__main__":
    main()
