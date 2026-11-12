"""pyuvm bench for NanoXL's requant.sv (contract C2), built on the MLACC-UVM patterns:
active input agent with idle gaps, reactive output agent with backpressure bursts,
falling-edge monitors, an in-order scoreboard against ref.py, a per-cycle model of the
saturation counter, and functional coverage written to JSON for run.py to merge.

Tests (select with UVM_TEST): smoke_test, random_test, stress_test, corner_test.
"""
import json
import os
import random
import sys
from pathlib import Path

import cocotb
import pyuvm
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, NullTrigger, RisingEdge
from pyuvm import (ConfigDB, uvm_agent, uvm_analysis_port, uvm_component, uvm_driver, uvm_env,
                   uvm_monitor, uvm_sequence, uvm_sequence_item, uvm_sequencer, uvm_subscriber,
                   uvm_test)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ref  # noqa: E402

L = int(os.environ.get("RQ_L", "4"))
M32 = (1 << 32) - 1
I32 = (ref.INT32_MIN, ref.INT32_MAX)


def s(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


# --------------------------------------------------------------------------- config
class RqCfg:
    def __init__(self, dut):
        self.dut = dut
        self.idle_prob = 0.2          # idle cycle between input beats
        self.stall_prob = 0.0         # chance out_ready drops in a cycle
        self.stall_burst = (1, 1)
        self.clr_prob = 0.0           # chance sat_clr pulses in a cycle
        self.reset_done = False

    async def start(self):
        cocotb.start_soon(Clock(self.dut.clk, 10, unit="ns").start())
        d = self.dut
        d.rst_n.value = 0
        for n in ("in_valid", "in_acc", "in_bias", "in_mult", "in_shift", "in_keep", "in_last",
                  "in_out16", "out_ready", "sat_clr"):
            getattr(d, n).value = 0
        for _ in range(4):
            await RisingEdge(d.clk)
        d.rst_n.value = 1
        await FallingEdge(d.clk)
        self.reset_done = True

    async def wait_reset(self):
        while not self.reset_done:
            await FallingEdge(self.dut.clk)


# --------------------------------------------------------------------------- items
class Beat(uvm_sequence_item):
    def __init__(self, name="beat", lanes=None, keep=None, last=0, out16=0):
        super().__init__(name)
        self.lanes = lanes or [(0, 0, 1 << 30, 0)] * L     # (acc, bias, mult, shift)
        self.keep = keep if keep is not None else [1] * L
        self.last, self.out16 = last, out16

    def __str__(self):
        return f"Beat(out16={self.out16} keep={self.keep} last={self.last} lanes={self.lanes})"


class OutBeat:
    def __init__(self, data, keep, sat, last):
        self.data, self.keep, self.sat, self.last = data, keep, sat, last


# --------------------------------------------------------------------------- input agent
class InDriver(uvm_driver):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")

    def drive(self, b):
        d = self.cfg.dut
        acc = bias = mult = shift = 0
        for i, (a, bi, m, sh) in enumerate(b.lanes):
            acc |= (a & M32) << (32 * i)
            bias |= (bi & M32) << (32 * i)
            mult |= (m & M32) << (32 * i)
            shift |= (sh & 31) << (5 * i)
        d.in_acc.value, d.in_bias.value, d.in_mult.value, d.in_shift.value = acc, bias, mult, shift
        d.in_keep.value = sum(k << i for i, k in enumerate(b.keep))
        d.in_last.value, d.in_out16.value = b.last, b.out16
        d.in_valid.value = 1

    async def run_phase(self):
        d = self.cfg.dut
        await self.cfg.wait_reset()
        item = None
        while True:
            if item is None:
                d.in_valid.value = 0
                item = await self.seq_item_port.get_next_item()
                await RisingEdge(d.clk)
            while random.random() < self.cfg.idle_prob:
                d.in_valid.value = 0
                await RisingEdge(d.clk)
            self.drive(item)
            while True:
                await FallingEdge(d.clk)
                fire = int(d.in_ready.value)
                await RisingEdge(d.clk)
                if fire:
                    break
            self.seq_item_port.item_done()
            item = None
            for _ in range(8):                      # allow back-to-back beats
                ok, nxt = self.seq_item_port.try_next_item()
                if ok:
                    item = nxt
                    break
                await NullTrigger()


class InMonitor(uvm_monitor):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        d = self.cfg.dut
        while True:
            await FallingEdge(d.clk)
            if int(d.rst_n.value) and int(d.in_valid.value) and int(d.in_ready.value):
                acc, bias, mult, shift = (int(d.in_acc.value), int(d.in_bias.value),
                                          int(d.in_mult.value), int(d.in_shift.value))
                lanes = [(s(acc >> 32 * i, 32), s(bias >> 32 * i, 32), s(mult >> 32 * i, 32),
                          (shift >> 5 * i) & 31) for i in range(L)]
                keep = [(int(d.in_keep.value) >> i) & 1 for i in range(L)]
                self.ap.write(Beat("mon", lanes, keep, int(d.in_last.value), int(d.in_out16.value)))


class InAgent(uvm_agent):
    def build_phase(self):
        self.seqr = uvm_sequencer("seqr", self)
        self.driver = InDriver("driver", self)
        self.monitor = InMonitor("monitor", self)

    def connect_phase(self):
        self.driver.seq_item_port.connect(self.seqr.seq_item_export)


# --------------------------------------------------------------------------- output side
class OutResponder(uvm_component):
    """Reactive: drives out_ready with random backpressure bursts and sat_clr pulses."""

    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")

    async def run_phase(self):
        d = self.cfg.dut
        await self.cfg.wait_reset()
        while True:
            await RisingEdge(d.clk)
            d.sat_clr.value = int(random.random() < self.cfg.clr_prob)
            if random.random() < self.cfg.stall_prob:
                d.out_ready.value = 0
                for _ in range(random.randint(*self.cfg.stall_burst) - 1):
                    await RisingEdge(d.clk)
                    d.sat_clr.value = int(random.random() < self.cfg.clr_prob)
            else:
                d.out_ready.value = 1


class CycleMonitor(uvm_monitor):
    """Everything on the pins each cycle (falling edge)."""

    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        d = self.cfg.dut
        await self.cfg.wait_reset()
        while True:
            await FallingEdge(d.clk)
            # control and counter outputs must never be X after reset; the datapath
            # registers are not reset, so out_* payload is only read when out_valid is 1
            snap = {k: int(getattr(d, k).value) for k in
                    ("in_valid", "in_ready", "out_valid", "out_ready", "sat_clr", "sat_count",
                     "sat_sticky")}
            for k in ("out_keep", "out_sat", "out_last", "out_data"):
                v = getattr(d, k).value
                snap[k] = int(v) if (snap["out_valid"] or v.is_resolvable) else 0
            self.ap.write(snap)


# --------------------------------------------------------------------------- checking
class Scoreboard(uvm_component):
    def build_phase(self):
        self.in_fifo = []
        self.errors = []
        self.checked = 0
        self.cyc = 0
        self.model_count = 0
        self.model_sticky = 0
        self.in_tap = _Tap("in_tap", self, self.on_in)
        self.cyc_tap = _Tap("cyc_tap", self, self.on_cycle)

    def on_in(self, b):
        exp = []
        for (a, bi, m, sh), k in zip(b.lanes, b.keep):
            exp.append(ref.requant_lane(a, bi, m, sh, b.out16) + (k,))
        self.in_fifo.append((b, exp))

    def err(self, msg):
        if len(self.errors) < 20:
            self.errors.append(f"cycle {self.cyc}: {msg}")

    def on_cycle(self, c):
        self.cyc += 1
        # saturation counter: registered value must equal the model before this edge
        if c["sat_count"] != self.model_count or c["sat_sticky"] != self.model_sticky:
            self.err(f"sat_count/sticky {c['sat_count']}/{c['sat_sticky']} "
                     f"!= model {self.model_count}/{self.model_sticky}")
            self.model_count, self.model_sticky = c["sat_count"], c["sat_sticky"]
        fire = c["out_valid"] and c["out_ready"]
        inc = bin(c["out_sat"]).count("1") if fire else 0
        self.model_count = min(M32, (0 if c["sat_clr"] else self.model_count) + inc)
        self.model_sticky = int((0 if c["sat_clr"] else self.model_sticky) or inc > 0)
        if not fire:
            return
        if not self.in_fifo:
            self.err("output beat with no input outstanding")
            return
        b, exp = self.in_fifo.pop(0)
        if c["out_last"] != b.last:
            self.err(f"out_last {c['out_last']} != {b.last}")
        for i, (want, sat, k) in enumerate(exp):
            if ((c["out_keep"] >> i) & 1) != k:
                self.err(f"lane {i} keep mismatch")
            got = s(c["out_data"] >> 16 * i, 16)
            if got != want:
                self.err(f"lane {i}: got {got}, want {want} for {b.lanes[i]} out16={b.out16}")
            if ((c["out_sat"] >> i) & 1) != (sat and k):
                self.err(f"lane {i}: sat {(c['out_sat'] >> i) & 1}, want {int(sat and k)}")
        self.checked += 1

    def check_phase(self):
        assert not self.errors, "scoreboard: " + " | ".join(self.errors)
        assert not self.in_fifo, f"scoreboard: {len(self.in_fifo)} input beats never came out"
        assert self.checked > 0, "scoreboard: nothing checked"


class _Tap(uvm_subscriber):
    def __init__(self, name, parent, fn):
        super().__init__(name, parent)
        self.fn = fn

    def write(self, t):
        self.fn(t)


BINS = (["mode_x_result." + m + "." + r for m in ("out8", "out16")
         for r in ("in_range", "zero", "sat_hi", "sat_lo")]
        + ["shift.zero", "shift.mid", "shift.max", "round.tie", "bias.wrap",
           "srdhm.overflow", "mult.min_legal", "mult.max",
           "flow.backpressure", "flow.back_to_back", "flow.partial_keep", "flow.last",
           "flow.clr_with_sat_event", "flow.counter_clear"])


class Coverage(uvm_component):
    def build_phase(self):
        self.hits = {b: 0 for b in BINS}
        self.prev_fire_in = 0
        self.in_tap = _Tap("in_tap", self, self.on_in)
        self.cyc_tap = _Tap("cyc_tap", self, self.on_cycle)

    def on_in(self, b):
        h = self.hits
        mode = "out16" if b.out16 else "out8"
        for (a, bi, m, sh), k in zip(b.lanes, b.keep):
            if not k:
                continue
            y, sat = ref.requant_lane(a, bi, m, sh, b.out16)
            r = "zero" if y == 0 else ("sat_hi" if sat and y > 0 else "sat_lo" if sat else "in_range")
            h[f"mode_x_result.{mode}.{r}"] += 1
            h["shift.zero" if sh == 0 else "shift.max" if sh == 31 else "shift.mid"] += 1
            h["round.tie"] += ref.is_tie(a, bi, m, sh)
            h["bias.wrap"] += not (I32[0] <= a + bi <= I32[1])
            h["srdhm.overflow"] += (ref.wrap32(a + bi) == I32[0] and m == I32[0])
            h["mult.min_legal"] += m == 1 << 30
            h["mult.max"] += m == I32[1]
        h["flow.partial_keep"] += 0 < sum(b.keep) < L
        h["flow.last"] += b.last

    def on_cycle(self, c):
        h = self.hits
        h["flow.backpressure"] += c["out_valid"] and not c["out_ready"]
        fire_in = c["in_valid"] and c["in_ready"]
        h["flow.back_to_back"] += fire_in and self.prev_fire_in
        self.prev_fire_in = fire_in
        fire = c["out_valid"] and c["out_ready"]
        h["flow.clr_with_sat_event"] += c["sat_clr"] and fire and c["out_sat"] != 0
        h["flow.counter_clear"] += c["sat_clr"] and c["sat_count"] != 0

    def report_phase(self):
        path = os.environ.get("RQ_COV")
        if path:
            Path(path).write_text(json.dumps(self.hits))


class RqEnv(uvm_env):
    def build_phase(self):
        self.inp = InAgent("inp", self)
        self.resp = OutResponder("resp", self)
        self.cyc = CycleMonitor("cyc", self)
        self.sb = Scoreboard("sb", self)
        self.cov = Coverage("cov", self)

    def connect_phase(self):
        self.inp.monitor.ap.connect(self.sb.in_tap.analysis_export)
        self.inp.monitor.ap.connect(self.cov.in_tap.analysis_export)
        self.cyc.ap.connect(self.sb.cyc_tap.analysis_export)
        self.cyc.ap.connect(self.cov.cyc_tap.analysis_export)


# --------------------------------------------------------------------------- sequences
def rand_lane(rng):
    shift = rng.choice([0, 31] + [rng.randrange(32)] * 6)
    mult = rng.choice([1 << 30, I32[1]] + [rng.randrange(1 << 30, 1 << 31)] * 6)
    r = rng.random()
    if r < 0.35:
        mag = 1 << min(31, shift + rng.randrange(2, 20))
        acc = rng.randrange(-mag, mag)
    elif r < 0.7:
        acc = rng.randrange(*I32)
    else:
        acc = max(min(rng.choice([I32[0], I32[1], 0, -1, 1]) + rng.randrange(-2, 3), I32[1]), I32[0])
    bias = rng.choice([0, 0, rng.randrange(-1000, 1000), rng.randrange(*I32)])
    if shift and rng.random() < 0.1:              # exact rdivpot tie via mult = 2^30
        q = (2 * rng.randrange(-(1 << 9), 1 << 9) + 1) << (shift - 1)
        if I32[0] <= 2 * q <= I32[1]:
            acc, bias, mult = 2 * q, 0, 1 << 30
    return (acc, bias, mult, shift)


class RandSeq(uvm_sequence):
    def __init__(self, name="rand", n=200, rng=None):
        super().__init__(name)
        self.n, self.rng = n, rng or random.Random()

    async def body(self):
        rng = self.rng
        for k in range(self.n):
            keep = [1] * L if rng.random() < 0.8 else [rng.randrange(2) for _ in range(L)]
            b = Beat("b", [rand_lane(rng) for _ in range(L)], keep, int(rng.random() < 0.1),
                     int(rng.random() < 0.5))
            await self.start_item(b)
            await self.finish_item(b)


def corner_lanes():
    """Directed lanes: extremes, ties at every shift, the srdhm overflow, bias wraps."""
    out = []
    for sh in range(32):
        out.append((1 << sh, 0, 1 << 30, sh))                     # exact tie, positive
        out.append((-(1 << sh), 0, 1 << 30, sh))                  # exact tie, negative
    for a in (I32[0], I32[1], 0, -1, 1):
        for m in (1 << 30, I32[1], I32[0]):
            for sh in (0, 1, 31):
                out.append((a, 0, m, sh))
    out += [(I32[1], 1, 1 << 30, 0), (I32[0], -1, 1 << 30, 0),   # bias wraps
            (I32[0], 0, I32[0], 0), (0, I32[0], I32[0], 0)]       # srdhm(INT32_MIN, INT32_MIN)
    return out


class CornerSeq(uvm_sequence):
    async def body(self):
        lanes = corner_lanes()
        for out16 in (0, 1):
            for k in range(0, len(lanes), L):
                chunk = (lanes[k:k + L] + [(0, 0, 1 << 30, 0)] * L)[:L]
                b = Beat("c", chunk, [1] * L, int(k + L >= len(lanes)), out16)
                await self.start_item(b)
                await self.finish_item(b)


# --------------------------------------------------------------------------- tests
class RqBaseTest(uvm_test):
    def build_phase(self):
        self.cfg = RqCfg(cocotb.top)
        self.configure(self.cfg)
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = RqEnv("env", self)

    def configure(self, cfg):
        pass

    async def run_phase(self):
        self.raise_objection()
        await self.cfg.start()
        await self.body()
        d = self.cfg.dut
        for _ in range(2000):                       # drain
            await RisingEdge(d.clk)
            if not self.env.sb.in_fifo:
                break
        for _ in range(4):
            await RisingEdge(d.clk)
        self.drop_objection()

    async def body(self):
        pass

    def rng(self):
        return random.Random(int(os.environ.get("COCOTB_RANDOM_SEED", "1")))


@pyuvm.test()
class smoke_test(RqBaseTest):
    async def body(self):
        await RandSeq("s", 30, self.rng()).start(self.env.inp.seqr)


@pyuvm.test()
class random_test(RqBaseTest):
    def configure(self, cfg):
        cfg.stall_prob, cfg.stall_burst, cfg.clr_prob = 0.2, (1, 4), 0.01

    async def body(self):
        await RandSeq("r", 1500, self.rng()).start(self.env.inp.seqr)


@pyuvm.test()
class stress_test(RqBaseTest):
    """Heavy backpressure, long stalls, no idle gaps, frequent counter clears."""

    def configure(self, cfg):
        cfg.idle_prob, cfg.stall_prob, cfg.stall_burst, cfg.clr_prob = 0.0, 0.5, (1, 12), 0.08

    async def body(self):
        await RandSeq("st", 1000, self.rng()).start(self.env.inp.seqr)


@pyuvm.test()
class corner_test(RqBaseTest):
    def configure(self, cfg):
        cfg.stall_prob, cfg.clr_prob = 0.3, 0.05

    async def body(self):
        await CornerSeq("c").start(self.env.inp.seqr)
