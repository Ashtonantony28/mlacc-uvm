"""Regenerate fixtures/c2_cases.json from a nanoxl-accelerator checkout.

    python3 ip/nanoxl_requant/gen_fixture.py --nx ../nanoxl-accelerator

The expected values come from NanoXL's numpy model (nanoxl.numerics.requant), so
ref.py and the bench are pinned to NanoXL's own definition. Regenerating is a
reviewed change.
"""
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
N = 6000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nx", required=True, type=Path)
    a = ap.parse_args()
    sys.path.insert(0, str(a.nx.resolve()))
    import numpy as np
    from nanoxl import numerics as nx
    commit = subprocess.run(["git", "-C", str(a.nx), "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=True).stdout.strip()
    rng = random.Random(7)
    I32 = (-(1 << 31), (1 << 31) - 1)
    cases = []
    for k in range(N):
        shift = rng.choice([0, 31, rng.randrange(32)])
        mult = rng.choice([1 << 30, I32[1], rng.randrange(1 << 30, 1 << 31)])
        r = rng.random()
        if r < 0.3:
            acc = rng.randrange(*I32)
        elif r < 0.6:
            mag = 1 << min(31, shift + rng.randrange(2, 20))
            acc = rng.randrange(-mag, mag)
        else:
            acc = rng.choice([I32[0], I32[1], 0, -1, 1]) + rng.randrange(-2, 3)
            acc = max(min(acc, I32[1]), I32[0])
        bias = rng.choice([0, rng.randrange(*I32), rng.randrange(-1000, 1000)])
        if k % 7 == 0 and shift > 0:          # force exact rdivpot ties
            q = (2 * rng.randrange(-(1 << 10), 1 << 10) + 1) << (shift - 1)
            if I32[0] <= q <= I32[1]:
                # pick acc so that srdhm(acc, 2^30) == acc/2 ... use mult = 2^30 path
                mult, bias, acc = 1 << 30, 0, max(min(2 * q, I32[1]), I32[0])
        out16 = rng.random() < 0.5
        want = int(nx.requant(np.array([acc]), np.array([mult]), np.array([shift]),
                              np.array([bias]), 16 if out16 else 8)[0])
        cases.append([acc, bias, mult, shift, int(out16), want])
    (HERE / "fixtures" / "c2_cases.json").write_text(json.dumps(
        {"source": {"repo": "Ashtonantony28/nanoxl-accelerator", "commit": commit,
                    "generator": f"nanoxl.numerics.requant, random.Random(7), {N} cases"},
         "cases": cases}, separators=(",", ":")) + "\n")
    print(f"wrote {N} cases from nanoxl-accelerator {commit[:7]}")


if __name__ == "__main__":
    main()
