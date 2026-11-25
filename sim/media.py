#!/usr/bin/env python3
"""README media for MLACC-UVM, all from real runs of this bench.

  python3 sim/media.py [--out docs/media]

  waveform-csr-traffic.png  Icarus waveform (WAVES=1, fst2vcd) of csr_traffic_test seed 1000
  coverage-closure.{gif,png} the 150 functional-coverage bins filling run by run over the
                            default regression (sim/run_regression.py; reuses reports/raw/regression)
  mutation-matrix.png       which tests kill which of the 15 injected RTL bugs (docs/MUTATION.md)
Needs iverilog, cocotb, pyuvm, matplotlib, ffmpeg and fst2vcd (gtkwave).
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

SIM = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SIM)
sys.path.insert(0, SIM)
from wavedraw import BG, DIM, GRID, PANEL, TXT, draw, parse_vcd  # noqa: E402

OPS = {0: "dot8", 1: "dot8u", 2: "dot8su", 4: "macc", 5: "rqs", 3: "ill", 6: "ill", 7: "ill"}
REGS = {0x000: "ID", 0x004: "VERSION", 0x008: "CTRL", 0x00C: "STATUS", 0x010: "MLSTAT", 0x014: "IRQ_STATUS",
        0x018: "CMD_COUNT", 0x01C: "RSP_COUNT", 0x020: "SCRATCH"}
ORDER = ["smoke_test", "reg_test", "corner_test", "irq_test", "random_test", "stress_test", "csr_traffic_test",
         "reset_midflight_test", "rqs_overflow_test"]


def waveform(out, test="csr_traffic_test", seed=1000, window=48):
    env = dict(os.environ)
    subprocess.run(["make", "-s", "-C", SIM, "TEST=test_mlacc", f"UVM_TEST={test}", f"SEED={seed}", "WAVES=1"], env=env,
                   check=True, capture_output=True)
    vcd = os.path.join(tempfile.mkdtemp(), "w.vcd")
    subprocess.run(["fst2vcd", os.path.join(SIM, "sim_build", "mlacc_top.fst"), "-o", vcd], check=True, capture_output=True)
    names = ["clk", "psel", "penable", "pwrite", "paddr", "cmd_valid", "cmd_ready", "cmd_op", "cmd_tag", "rsp_valid",
             "rsp_ready", "rsp_tag", "fifo_count", "irq"]
    d, w = parse_vcd(vcd, names)
    P = d["clk"][2][0] - d["clk"][0][0]
    T = d["clk"][-1][0]
    best = None                                   # the busiest window: APB, both handshakes, irq
    for start in range(20 * P, T - window * P, 4 * P):
        end = start + window * P
        sc = sum(min(8, sum(1 for t, _ in d[n] if start < t < end)) * k for n, k in
                 (("psel", 3), ("cmd_ready", 2), ("rsp_ready", 1), ("irq", 4), ("rsp_valid", 2), ("cmd_valid", 2)))
        if best is None or sc > best[0]:
            best = (sc, start)
    t0 = best[1] - best[1] % P
    rows = [("APB3 (CSR)", None, TXT), ("psel", "psel", "#d2a8ff"), ("penable", "penable", "#d2a8ff"),
            ("pwrite", "pwrite", "#d2a8ff"), ("paddr", "paddr", "#d2a8ff"),
            ("command stream", None, TXT), ("cmd_valid", "cmd_valid", "#58a6ff"), ("cmd_ready", "cmd_ready", "#58a6ff"),
            ("cmd_op", "cmd_op", "#58a6ff"), ("cmd_tag", "cmd_tag", "#58a6ff"),
            ("result FIFO", None, TXT), ("fifo_count", "fifo_count", "#3fb950"), ("rsp_valid", "rsp_valid", "#f0883e"),
            ("rsp_ready", "rsp_ready", "#f0883e"), ("rsp_tag", "rsp_tag", "#f0883e"),
            ("interrupt", None, TXT), ("irq", "irq", "#ff7b72")]
    draw(d, w, rows, t0, t0 + window * P, P, os.path.join(out, "waveform-csr-traffic.png"),
         "MLACC: CSR traffic alongside data traffic",
         f"Icarus RTL waveform, {test} seed {seed} (pyuvm bench): APB reads/writes, credit-gated cmd_ready, "
         "random rsp_ready stalls, FIFO level, interrupt",
         fmt={"cmd_op": lambda v: OPS.get(v, "?"), "paddr": lambda v: REGS.get(v, hex(v)), "cmd_tag": str, "rsp_tag": str})


def closure(out, fps=6):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cov = os.path.join(ROOT, "reports", "raw", "regression", "cov")
    if not glob.glob(os.path.join(cov, "*.json")):
        subprocess.run([sys.executable, os.path.join(SIM, "run_regression.py")], check=True)
    paths = sorted(glob.glob(os.path.join(cov, "*.json")),
                   key=lambda p: (ORDER.index(os.path.basename(p).split(".")[0]), p))
    runs = [json.load(open(p)) for p in paths]
    bins = []                                     # (coverpoint, bin) in report order
    for g, items in runs[0].items():
        for it, bb in items.items():
            for b in bb:
                bins.append((f"{g}.{it}", b))
    cps = []
    for cp, _ in bins:
        if cp not in cps:
            cps.append(cp)
    first = {}
    for r, d in enumerate(runs):
        for g, items in d.items():
            for it, bb in items.items():
                for b, n in bb.items():
                    if n and (f"{g}.{it}", b) not in first:
                        first[f"{g}.{it}", b] = r
    tests = [os.path.basename(p).rsplit(".", 1)[0] for p in paths]
    palette = {t: c for t, c in zip(ORDER, ["#58a6ff", "#d2a8ff", "#f0883e", "#ff7b72", "#3fb950", "#e3b341", "#79c0ff",
                                            "#ffa198", "#a5d6ff"])}
    cols = 30
    tmp = tempfile.mkdtemp()
    nfr = len(runs) + 1
    for f in range(nfr + 3 * fps):
        upto = min(f, len(runs)) - 1
        fig = plt.figure(figsize=(12.8, 6.6), dpi=100, facecolor=BG)
        ax = fig.add_axes([0.03, 0.10, 0.56, 0.72])
        ax2 = fig.add_axes([0.66, 0.26, 0.31, 0.54])
        ax.set_facecolor(BG)
        ax.set_xlim(-0.6, cols - 0.4)
        ax.set_aspect("equal")
        ax.axis("off")
        x = y = 0
        last_cp = None
        ax.text(-0.6, 0.75, "cg_cmd: ops × operand classes, rqs shifts/outcomes, macc", color=DIM, fontsize=8.5)
        for cp, b in bins:
            if last_cp is not None and cp.split(".")[0] != last_cp.split(".")[0]:
                y += 2.2
                x = 0
                lab = {"cg_flow": "cg_flow: FIFO levels, stalls, back-pressure, irq sources, W1C races, reset",
                       "cg_csr": "cg_csr: every register × read/write"}.get(cp.split(".")[0], cp.split(".")[0])
                ax.text(-0.6, -y + 0.75, lab, color=DIM, fontsize=8.5)
            elif x >= cols:
                x, y = 0, y + 1
            last_cp = cp
            r = first.get((cp, b), 99)
            hit = r <= upto
            ax.add_patch(plt.Rectangle((x - 0.42, -y - 0.42), 0.84, 0.84,
                                       color=palette[tests[r].split(".")[0]] if hit else PANEL,
                                       ec=GRID if not hit else "none", lw=0.6))
            x += 1
        ax.set_ylim(-y - 0.8, 0.8)
        for g, yy in (("cg_cmd", 0), ):
            pass
        hits = sum(1 for k in bins if first.get(k, 99) <= upto)
        ax.text(-0.6, 2.2, f"{hits}/{len(bins)} bins", color=TXT, fontsize=14, weight="bold", transform=ax.transData)
        xs = list(range(1, len(runs) + 1))
        cum = [sum(1 for k in bins if first.get(k, 99) <= r) for r in range(len(runs))]
        ax2.set_facecolor(PANEL)
        ax2.grid(color=GRID, lw=0.6)
        ax2.set_xlim(0, len(runs) + 1)
        ax2.set_ylim(0, 100)
        ax2.plot(xs, [100 * c / len(bins) for c in cum], color=GRID, lw=1)
        n = max(0, upto + 1)
        if n:
            for i in range(n):
                ax2.bar(i + 1, 100 * cum[i] / len(bins), color=palette[tests[i].split(".")[0]], width=0.8)
        ax2.set_xlabel("regression run", color=DIM)
        ax2.set_ylabel("functional coverage  %", color=DIM)
        ax2.tick_params(colors=DIM)
        for s_ in ax2.spines.values():
            s_.set_color(GRID)
        cur = tests[upto] if upto >= 0 else ""
        ax2.set_title(cur, color=TXT, fontsize=11, family="DejaVu Sans Mono")
        for k, t in enumerate(ORDER):
            fig.text(0.66 + 0.105 * (k % 3), 0.10 - 0.035 * (k // 3), "■ " + t.replace("_test", ""), color=palette[t],
                     fontsize=8.5)
        fig.text(0.03, 0.93, "MLACC-UVM: functional coverage closure", color=TXT, fontsize=17, weight="bold")
        fig.text(0.03, 0.89, f"Each square is one of the {len(bins)} coverage bins (21 coverpoints and crosses), coloured by "
                 "the test that first hit it. Real coverage data from the 30-run regression.", color=DIM, fontsize=9.5)
        fig.savefig(os.path.join(tmp, f"f{f:03d}.png"), facecolor=BG)
        if f == nfr + 3 * fps - 1:
            fig.savefig(os.path.join(out, "coverage-closure.png"), facecolor=BG)
        plt.close(fig)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", os.path.join(tmp, "f%03d.png"), "-vf",
                    "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=none",
                    os.path.join(out, "coverage-closure.gif")], check=True)


def mutation(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = []
    for line in open(os.path.join(ROOT, "docs", "MUTATION.md")):
        m = re.match(r"\| `(MUTANT_\w+)` \| (\w+) \| (.+?) \| (.+?) \|", line)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3), [t.strip() for t in m.group(4).split(",")]))
    fig, ax = plt.subplots(figsize=(12.8, 7.0), dpi=100, facecolor=BG)
    fig.subplots_adjust(left=0.40, right=0.94, top=0.80, bottom=0.04)
    ax.set_facecolor(BG)
    area_col = {"CSR": "#d2a8ff", "Flow": "#58a6ff", "Datapath": "#f0883e"}
    for i, (mu, area, desc, killed) in enumerate(rows):
        for j, t in enumerate(ORDER):
            k = t in killed
            ax.add_patch(plt.Rectangle((j + 0.06, -i - 0.94), 0.88, 0.88, color=area_col[area] if k else PANEL, alpha=0.9 if k else 1))
        ax.text(-0.25, -i - 0.5, desc if len(desc) < 62 else desc[:59] + "...", color=TXT, fontsize=8.6, ha="right", va="center")
        ax.text(-0.25 - 0, -i - 0.5, "", fontsize=1)
    ax.set_xlim(0, len(ORDER))
    ax.set_ylim(-len(rows), 0)
    ax.set_xticks([j + 0.5 for j in range(len(ORDER))])
    ax.set_xticklabels([t.replace("_test", "") for t in ORDER], rotation=35, ha="left", color=DIM, fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks([])
    for s_ in ax.spines.values():
        s_.set_visible(False)
    ax.tick_params(length=0)
    fig.text(0.02, 0.95, f"MLACC-UVM: {len(rows)}/{len(rows)} injected RTL bugs caught", color=TXT, fontsize=17, weight="bold")
    fig.text(0.02, 0.915, "Mutation campaign (python3 sim/mutants.py): a filled cell means that test fails on that mutant. "
             "Colour = area:", color=DIM, fontsize=9.5)
    for k, (a, c) in enumerate(area_col.items()):
        fig.text(0.02 + 0.08 * k, 0.88, "■ " + a, color=c, fontsize=10)
    fig.savefig(os.path.join(out, "mutation-matrix.png"), facecolor=BG)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "media"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    waveform(a.out)
    closure(a.out)
    mutation(a.out)
    print("\n".join(sorted(glob.glob(os.path.join(a.out, "*")))))


if __name__ == "__main__":
    main()
