"""Minimal VCD parser + dark-theme waveform renderer (matplotlib), shared template."""
import math
import re

BG, PANEL, GRID, TXT, DIM = "#0d1117", "#161b22", "#30363d", "#e6edf3", "#8b949e"


def parse_vcd(path, names, scope=None):
    """Return {name: [(t, value_str)]} for signals `names` in the first scope (or `scope`)."""
    want, ids, widths = set(names), {}, {}
    depth, cur_scope, first_scope = 0, [], None
    data = {n: [] for n in names}
    t = 0
    with open(path) as fh:
        header = True
        for line in fh:
            s = line.strip()
            if header:
                if s.startswith("$scope"):
                    nm = s.split()[2]
                    cur_scope.append(nm)
                    if first_scope is None:
                        first_scope = nm
                elif s.startswith("$upscope"):
                    cur_scope.pop()
                elif s.startswith("$var"):
                    p = s.split()
                    w, code, nm = int(p[2]), p[3], p[4]
                    target = scope or first_scope
                    if nm in want and cur_scope and cur_scope[-1] == target and nm not in ids.values():
                        ids.setdefault(code, nm)
                        widths[nm] = w
                elif s.startswith("$enddefinitions"):
                    header = False
                continue
            if not s:
                continue
            c = s[0]
            if c == "#":
                t = int(s[1:])
            elif c in "01xzXZ":
                code = s[1:]
                if code in ids:
                    data[ids[code]].append((t, s[0]))
            elif c in "bB":
                v, code = s[1:].split()
                if code in ids:
                    data[ids[code]].append((t, v))
    return data, widths


def value_at(series, t):
    v = None
    for tt, vv in series:
        if tt > t:
            break
        v = vv
    return v


def to_int(v):
    try:
        return int(v, 2)
    except (TypeError, ValueError):
        return None


def draw(data, widths, rows, t0, t1, period, out, title, subtitle, fmt=None, highlight=None, figw=12.8):
    """rows: list of (label, signal or None for a group header, color). Bus values formatted by fmt[name](int)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fmt = fmt or {}
    n = len(rows)
    rh = 0.42
    fig = plt.figure(figsize=(figw, 1.3 + n * rh), dpi=110, facecolor=BG)
    ax = fig.add_axes([0.16, 0.06, 0.82, 1 - (1.0 / (1.3 + n * rh)) - 0.06])
    ax.set_facecolor(PANEL)
    ax.set_xlim(t0, t1)
    ax.set_ylim(-n, 0.2)
    ax.set_yticks([])
    for s_ in ax.spines.values():
        s_.set_visible(False)
    ncyc = int((t1 - t0) / period)
    for k in range(ncyc + 1):
        x = t0 + k * period
        ax.axvline(x, color=GRID, lw=0.5, alpha=0.6, zorder=0)
    ax.set_xticks([t0 + k * period for k in range(0, ncyc + 1, 5)])
    ax.set_xticklabels([str(k) for k in range(0, ncyc + 1, 5)], color=DIM, fontsize=8)
    ax.set_xlabel("clock cycle (window)", color=DIM, fontsize=8)
    if highlight:
        for (a, b, lab, col) in highlight:
            ax.axvspan(a, b, color=col, alpha=0.10, zorder=0)
            ax.text((a + b) / 2, 0.08, lab, color=col, fontsize=8, ha="center", va="bottom")
    for i, (label, sig, col) in enumerate(rows):
        y0 = -i - 0.8
        y1 = -i - 0.2
        fig.text(0.155, 0, "", fontsize=1)
        if sig is None:
            ax.text(t0 - (t1 - t0) * 0.012, (y0 + y1) / 2, label, color=TXT, fontsize=9.5, weight="bold", ha="right", va="center",
                    clip_on=False)
            ax.axhline(y1 + 0.3, color=GRID, lw=0.8)
            continue
        ax.text(t0 - (t1 - t0) * 0.012, (y0 + y1) / 2, label, color=DIM, fontsize=9, ha="right", va="center",
                clip_on=False, family="DejaVu Sans Mono")
        ser = data[sig]
        pts = [(t0, value_at(ser, t0))] + [(tt, vv) for tt, vv in ser if t0 < tt < t1] + [(t1, None)]
        w = widths.get(sig, 1)
        if sig == "clk":
            xs, ys = [], []
            for k in range(ncyc * 2 + 1):
                x = t0 + k * period / 2
                v = 1 if k % 2 == 0 else 0
                xs += [x, x]
                ys += [ys[-1] if ys else v, v]
            ax.plot(xs, [y0 + (y1 - y0) * v for v in ys], color=col, lw=1.0)
            continue
        for (ta, va), (tb, _) in zip(pts[:-1], pts[1:]):
            if w == 1:
                lv = 1 if va == "1" else 0
                yy = y0 + (y1 - y0) * lv
                ax.plot([ta, tb], [yy, yy], color=col if lv else col, lw=1.6, alpha=1.0 if lv else 0.75)
                ax.plot([tb, tb], [y0, y1], color=col, lw=0.6, alpha=0.25)
                if lv:
                    ax.fill_between([ta, tb], y0, yy, color=col, alpha=0.12, lw=0)
            else:
                iv = to_int(va)
                m = min(period * 0.15, (tb - ta) / 2)
                xs = [ta, ta + m, tb - m, tb, tb - m, ta + m, ta]
                ys = [(y0 + y1) / 2, y1, y1, (y0 + y1) / 2, y0, y0, (y0 + y1) / 2]
                ax.fill(xs, ys, color=col, alpha=0.18 if iv else 0.06, lw=0)
                ax.plot(xs, ys, color=col, lw=1.0, alpha=0.9)
                if iv is not None and (tb - ta) >= period * (0.9 if len(fmt[sig](iv) if sig in fmt else str(iv)) <= 3 else 1.8):
                    s = fmt[sig](iv) if sig in fmt else (f"{iv:x}" if iv > 9 else str(iv))
                    if s:
                        ax.text((ta + tb) / 2, (y0 + y1) / 2, s, color=TXT, fontsize=7.5, ha="center", va="center",
                                family="DejaVu Sans Mono", clip_on=True)
    fig.text(0.02, 1 - 0.32 / (1.3 + n * rh), title, color=TXT, fontsize=15, weight="bold")
    fig.text(0.02, 1 - 0.62 / (1.3 + n * rh), subtitle, color=DIM, fontsize=9)
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
