#!/usr/bin/env python3
"""Merge per-run coverage JSON files and print / write a Markdown coverage report.

  python3 sim/coverage_report.py reports/raw/regression/cov [--md docs/COVERAGE.md]
"""
import argparse
import glob
import json
import os


def merge(paths):
    tot = {}
    for p in paths:
        with open(p) as fh:
            d = json.load(fh)
        for g, items in d.items():
            for it, bins in items.items():
                dst = tot.setdefault(f"{g}.{it}", {})
                for b, n in bins.items():
                    dst[b] = dst.get(b, 0) + n
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cov_dir")
    ap.add_argument("--md")
    a = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(a.cov_dir, "*.json")))
    tot = merge(paths)
    hit_all = sum(1 for b in tot.values() for n in b.values() if n)
    n_all = sum(len(b) for b in tot.values())
    lines = [f"# Functional coverage\n",
             f"Merged from {len(paths)} runs. **{hit_all}/{n_all} bins = "
             f"{100.0 * hit_all / n_all:.1f}%**\n",
             "| Coverpoint / cross | Bins hit | % | Holes |", "|---|---|---|---|"]
    for name, bins in tot.items():
        hit = sum(1 for n in bins.values() if n)
        holes = ", ".join(b for b, n in bins.items() if not n)
        lines.append(f"| `{name}` | {hit}/{len(bins)} | {100.0 * hit / len(bins):.0f}% | {holes or '-'} |")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.md:
        with open(a.md, "w") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
