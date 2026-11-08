"""Functional coverage: a small covergroup library plus the MLACC coverage model.

pyuvm has no covergroups, so Coverpoint/Cross/Covergroup implement the subset of
SystemVerilog semantics we need (named bins, sampled by a function, crosses with
ignore filters). Results are dumped as JSON per run and merged by
sim/coverage_report.py into docs/COVERAGE.md.
"""
import json
import os
from itertools import product

from pyuvm import uvm_component

from mlacc_tb.scoreboard import _Tap, MAPPED
from mlacc_tb.stream_agents import ResetEvent
from mlacc_tb.xmlacc_model import dot8

MASK64 = (1 << 64) - 1


class Coverpoint:
    def __init__(self, name, bins):
        self.name, self.bins = name, list(bins)
        self.hits = {b: 0 for b in self.bins}
        self.illegal = []          # values outside every bin (SV illegal_bins semantics)

    def sample(self, b):
        if b is None:
            return
        if b not in self.hits:
            self.illegal.append(b)
            return
        self.hits[b] += 1


class Cross:
    def __init__(self, name, a, b, ignore=lambda x, y: False):
        self.name = name
        self.bins = [(x, y) for x, y in product(a.bins, b.bins) if not ignore(x, y)]
        self.hits = {k: 0 for k in self.bins}

    def sample(self, x, y):
        if (x, y) in self.hits:
            self.hits[(x, y)] += 1


class Covergroup:
    def __init__(self, name):
        self.name = name
        self.items = {}

    def cp(self, name, bins):
        self.items[name] = Coverpoint(name, bins)
        return self.items[name]

    def cross(self, name, a, b, ignore=lambda x, y: False):
        self.items[name] = Cross(name, a, b, ignore)
        return self.items[name]

    def to_dict(self):
        return {n: {repr(k): v for k, v in it.hits.items()} for n, it in self.items.items()}


# ---------------------------------------------------------------- classifiers
def lane_class(v):
    """Classify a 64-bit operand by its int8 lanes."""
    v &= MASK64
    lanes = [(v >> (8 * i)) & 0xFF for i in range(8)]
    if v == 0:
        return "zero"
    if all(b == 0xFF for b in lanes):
        return "all_ones"
    if all(b == 0x7F for b in lanes):
        return "max_pos"
    if all(b == 0x80 for b in lanes):
        return "min_neg"
    if all(b in (0x00, 0x7F, 0x80, 0xFF) for b in lanes):
        return "mixed_extreme"
    return "random"


def to_s64(v):
    v &= MASK64
    return v - (1 << 64) if v >> 63 else v


def rqs_shift_bin(sh):
    if sh == 0:
        return "sh0"
    if sh == 1:
        return "sh1"
    if sh < 16:
        return "sh2_15"
    if sh < 32:
        return "sh16_31"
    if sh < 63:
        return "sh32_62"
    return "sh63"


def rqs_outcome(rs1, rs2):
    sh = rs2 & 63
    x = to_s64(rs1)
    rnd = (1 << (sh - 1)) if sh else 0
    if x + rnd > (1 << 63) - 1:
        return "add_overflow"           # rs1 + rnd exceeds int64 (spec corner)
    t = (x + rnd) >> sh
    return "sat_pos" if t > 127 else "sat_neg" if t < -128 else "in_range"


class MlaccCoverage(uvm_component):
    OP_NAMES = {0: "dot8", 1: "dot8u", 2: "dot8su", 4: "macc", 5: "rqs"}
    CLASSES = ["zero", "all_ones", "max_pos", "min_neg", "mixed_extreme", "random"]
    REG_NAMES = {0x000: "ID", 0x004: "VERSION", 0x008: "CTRL", 0x00C: "STATUS", 0x010: "MLSTAT",
                 0x014: "IRQ_STATUS", 0x018: "CMD_COUNT", 0x01C: "RSP_COUNT", 0x020: "SCRATCH"}

    def build_phase(self):
        self.cmd_tap = _Tap("cmd_tap", self, self.on_cmd)
        self.apb_tap = _Tap("apb_tap", self, self.on_apb)
        self.sig_tap = _Tap("sig_tap", self, self.on_cycle)

        g = self.cg_cmd = Covergroup("cg_cmd")
        self.cp_op = g.cp("op", list(self.OP_NAMES.values()) + ["illegal"])
        self.cp_rs1 = g.cp("rs1_class", self.CLASSES)
        self.cp_rs2 = g.cp("rs2_class", self.CLASSES)
        g.cross("op_x_rs1", self.cp_op, self.cp_rs1,
                ignore=lambda o, c: o in ("illegal", "rqs"))
        g.cross("op_x_rs2", self.cp_op, self.cp_rs2,
                ignore=lambda o, c: o in ("illegal", "rqs"))
        self.cp_sh = g.cp("rqs_shift", ["sh0", "sh1", "sh2_15", "sh16_31", "sh32_62", "sh63"])
        self.cp_rqs = g.cp("rqs_outcome", ["in_range", "sat_pos", "sat_neg", "add_overflow"])
        g.cross("rqs_shift_x_outcome", self.cp_sh, self.cp_rqs,
                ignore=lambda sh, o: (sh == "sh0" and o == "add_overflow") or
                                     (sh in ("sh32_62", "sh63") and o in ("sat_pos", "sat_neg")))
        self.cp_macc = g.cp("macc_acc", ["zero", "pos", "neg", "wraps"])

        f = self.cg_flow = Covergroup("cg_flow")
        self.cp_fifo = f.cp("fifo_level", [0, 1, 2, 3, 4])
        self.cp_cstall = f.cp("cmd_stall_reason", ["fifo_full", "disabled"])
        self.cp_bp = f.cp("rsp_backpressure", ["stalled", "stalled_while_full"])
        self.cp_b2b = f.cp("cmd_back_to_back", ["b2b"])
        self.cp_both = f.cp("cmd_and_rsp_same_cycle", ["both"])
        self.cp_irq = f.cp("irq_source", ["done", "sat", "err"])
        self.cp_coll = f.cp("w1c_set_collision", ["done", "sat", "err"])
        self.cp_ctrl_busy = f.cp("disable_while_busy", ["yes"])
        self.cp_rst = f.cp("reset_with_traffic", ["yes"])

        r = self.cg_csr = Covergroup("cg_csr")
        self.cp_reg = r.cp("reg", list(self.REG_NAMES.values()) + ["unmapped"])
        self.cp_dir = r.cp("dir", ["read", "write"])
        r.cross("reg_x_dir", self.cp_reg, self.cp_dir)
        self.prev = None
        self.busy_now = False

    # ---------------------------------------------------------------- samplers
    def on_cmd(self, c):
        op = self.OP_NAMES.get(c.op, "illegal")
        self.cp_op.sample(op)
        if op == "illegal":
            return
        c1, c2 = lane_class(c.rs1), lane_class(c.rs2)
        self.cp_rs1.sample(c1)
        self.cp_rs2.sample(c2) if op != "rqs" else None
        self.cg_cmd.items["op_x_rs1"].sample(op, c1)
        self.cg_cmd.items["op_x_rs2"].sample(op, c2)
        if op == "rqs":
            sh, out = rqs_shift_bin(c.rs2 & 63), rqs_outcome(c.rs1, c.rs2)
            self.cp_sh.sample(sh)
            self.cp_rqs.sample(out)
            self.cg_cmd.items["rqs_shift_x_outcome"].sample(sh, out)
        if op == "macc":
            acc = to_s64(c.rs3)
            total = acc + dot8(c.rs1, c.rs2)
            if total > (1 << 63) - 1 or total < -(1 << 63):
                self.cp_macc.sample("wraps")
            else:
                self.cp_macc.sample("zero" if acc == 0 else "pos" if acc > 0 else "neg")

    def on_apb(self, a):
        name = self.REG_NAMES.get(a.addr, "unmapped")
        d = "write" if a.write else "read"
        self.cp_reg.sample(name)
        self.cp_dir.sample(d)
        self.cg_csr.items["reg_x_dir"].sample(name, d)

    def on_cycle(self, s):
        if isinstance(s, ResetEvent):
            if self.busy_now:
                self.cp_rst.sample("yes")
            self.prev = None
            return
        p = self.prev
        self.prev = s
        self.busy_now = bool(s.s1_valid or s.fifo_count)
        self.cp_fifo.sample(s.fifo_count)
        if s.cmd_valid and not s.cmd_ready:
            self.cp_cstall.sample("fifo_full" if (s.fifo_count + s.s1_valid) >= 4 else "disabled")
        if s.rsp_valid and not s.rsp_ready:
            self.cp_bp.sample("stalled_while_full" if s.fifo_count == 4 else "stalled")
        cmd_fire, rsp_fire = s.cmd_valid and s.cmd_ready, s.rsp_valid and s.rsp_ready
        if cmd_fire and rsp_fire:
            self.cp_both.sample("both")
        if p is not None:
            if cmd_fire and p.cmd_valid and p.cmd_ready:
                self.cp_b2b.sample("b2b")
            if s.irq and not p.irq:
                for bit, src in enumerate(("done", "sat", "err")):
                    if (s.irq_sts >> bit) & 1 and s.irq_en >> bit & 1:
                        self.cp_irq.sample(src)
        apb_wr = s.psel and s.penable and s.apb_payload[0]
        if apb_wr:
            _w, addr, data = s.apb_payload
            if addr == 0x014:
                if data & 1 and rsp_fire:
                    self.cp_coll.sample("done")
                if data & 2 and s.ev_sat:
                    self.cp_coll.sample("sat")
                if data & 4 and s.ev_err:
                    self.cp_coll.sample("err")
            if addr == 0x008 and not (data & 1) and self.busy_now:
                self.cp_ctrl_busy.sample("yes")

    # ---------------------------------------------------------------- results
    def summary(self):
        out = {}
        for g in (self.cg_cmd, self.cg_flow, self.cg_csr):
            for n, it in g.items.items():
                hit = sum(1 for v in it.hits.values() if v)
                out[f"{g.name}.{n}"] = (hit, len(it.hits))
        return out

    def check_phase(self):
        bad = [(g.name, n, it.illegal[:3]) for g in (self.cg_cmd, self.cg_flow, self.cg_csr)
               for n, it in g.items.items() if getattr(it, "illegal", None)]
        if bad:
            raise AssertionError(f"illegal coverage bins hit: {bad}")

    def report_phase(self):
        s = self.summary()
        hit = sum(h for h, _ in s.values())
        tot = sum(t for _, t in s.values())
        self.logger.info(f"functional coverage: {hit}/{tot} bins = {100.0 * hit / tot:.1f}%")
        out_dir = os.environ.get("COV_DIR")
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            name = os.environ.get("COV_NAME", "run")
            with open(os.path.join(out_dir, f"{name}.json"), "w") as fh:
                json.dump({g.name: g.to_dict() for g in (self.cg_cmd, self.cg_flow, self.cg_csr)},
                          fh, indent=1)
