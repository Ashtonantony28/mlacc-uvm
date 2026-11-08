"""Sequences: constrained-random command traffic, register (RAL) sequences and
raw APB sequences.

pyuvm has no constraint solver, so each randomize() below is written as an
explicit constraint: a weighted distribution (`dist`) over operand classes and
value ranges, which is what the equivalent SV `constraint ... dist {}` blocks
would express.
"""
import random

from pyuvm import uvm_sequence, uvm_status_e

from mlacc_tb.apb_agent import ApbItem
from mlacc_tb.stream_agents import CmdItem
from mlacc_tb.ral import REG_SPEC, UNMAPPED_PROBES

MASK64 = (1 << 64) - 1
OP_CODES = {"dot8": 0, "dot8u": 1, "dot8su": 2, "macc": 4, "rqs": 5}
ILLEGAL = [3, 6, 7]


def dist(weights):
    """weights: {value: weight} -> one value (SV `dist` with := semantics)."""
    vals, w = zip(*weights.items())
    return random.choices(vals, weights=w)[0]


def lanes(bs):
    return sum((b & 0xFF) << (8 * i) for i, b in enumerate(bs))


def rand_operand(cls):
    if cls == "zero":
        return 0
    if cls == "all_ones":
        return MASK64
    if cls == "max_pos":
        return lanes([0x7F] * 8)
    if cls == "min_neg":
        return lanes([0x80] * 8)
    if cls == "mixed_extreme":
        while True:
            v = lanes(random.choice([0x00, 0x7F, 0x80, 0xFF]) for _ in range(8))
            if v not in (0, MASK64, lanes([0x7F] * 8), lanes([0x80] * 8)) and \
               any(b in (0x7F, 0x80) for b in v.to_bytes(8, "little")):
                return v
    return random.getrandbits(64)


class TrafficProfile:
    """Knobs for RandCmdSeq; the default is a balanced mix."""

    def __init__(self, **kw):
        self.op_w = {"dot8": 25, "dot8u": 15, "dot8su": 15, "macc": 20, "rqs": 20, "illegal": 2}
        self.class_w = {"zero": 5, "all_ones": 5, "max_pos": 8, "min_neg": 8,
                        "mixed_extreme": 14, "random": 60}
        self.shift_w = {"sh0": 6, "sh1": 6, "sh2_15": 40, "sh16_31": 30, "sh32_62": 12, "sh63": 6}
        self.rqs_val_w = {"int32": 50, "int8ish": 15, "big": 15, "near_max": 10, "random": 10}
        self.acc_w = {"zero": 15, "small": 45, "near_max": 15, "near_min": 15, "random": 10}
        self.__dict__.update(kw)


def rand_cmd(tag, prof):
    op_name = dist(prof.op_w)
    op = random.choice(ILLEGAL) if op_name == "illegal" else OP_CODES[op_name]
    rs1 = rand_operand(dist(prof.class_w))
    rs2 = rand_operand(dist(prof.class_w))
    rs3 = random.getrandbits(64)
    if op_name == "rqs":
        shb = dist(prof.shift_w)
        sh = {"sh0": 0, "sh1": 1, "sh2_15": random.randint(2, 15), "sh16_31": random.randint(16, 31),
              "sh32_62": random.randint(32, 62), "sh63": 63}[shb]
        rs2 = (random.getrandbits(58) << 6) | sh          # upper bits of rs2 must be ignored
        k = dist(prof.rqs_val_w)
        if k == "int32":
            rs1 = random.randint(-(1 << 31), (1 << 31) - 1)
        elif k == "int8ish":
            rs1 = random.randint(-200, 200) << sh if sh < 50 else random.randint(-200, 200)
        elif k == "big":
            rs1 = random.choice([-1, 1]) * random.randint(1 << 40, (1 << 62))
        elif k == "near_max":                               # rs1 + rnd may exceed int64
            rs1 = (1 << 63) - 1 - random.randint(0, 1 << max(sh - 1, 0))
        else:
            rs1 = random.getrandbits(64)
    if op_name == "macc":
        k = dist(prof.acc_w)
        rs3 = {"zero": 0, "small": random.randint(-(1 << 20), 1 << 20),
               "near_max": (1 << 63) - 1 - random.randint(0, 1 << 17),
               "near_min": -(1 << 63) + random.randint(0, 1 << 17),
               "random": random.getrandbits(64)}[k]
    return CmdItem("cmd", tag & 0xFF, op, rs1, rs2, rs3)


class _TagMixin:
    _next_tag = 0

    @classmethod
    def next_tag(cls):
        t = _TagMixin._next_tag
        _TagMixin._next_tag = (t + 1) & 0xFF
        return t


class RandCmdSeq(uvm_sequence, _TagMixin):
    def __init__(self, name="rand_cmd_seq", n=100, profile=None):
        super().__init__(name)
        self.n = n
        self.profile = profile or TrafficProfile()

    async def body(self):
        for _ in range(self.n):
            item = rand_cmd(self.next_tag(), self.profile)
            await self.start_item(item)
            await self.finish_item(item)


class DirectedCmdSeq(uvm_sequence, _TagMixin):
    """vectors: iterable of (op, rs1, rs2, rs3)."""

    def __init__(self, name="directed_cmd_seq", vectors=()):
        super().__init__(name)
        self.vectors = list(vectors)

    async def body(self):
        for op, a, b, c in self.vectors:
            item = CmdItem("cmd", self.next_tag(), op, a, b, c)
            await self.start_item(item)
            await self.finish_item(item)


def corner_vectors():
    """Hand-picked spec corners for every op."""
    M = MASK64
    P, N = lanes([0x7F] * 8), lanes([0x80] * 8)
    v = []
    for op in (0, 1, 2, 4):
        for a, b in [(0, 0), (M, M), (P, P), (N, N), (P, N), (N, P), (N, M), (M, N),
                     (lanes([1, -1, 2, -2, 127, -128, 0, 5]), lanes([3, 3, 3, 3, 1, 1, 9, 9]))]:
            v.append((op, a, b, 0))
    for acc in [(1 << 63) - 1, -(1 << 63), -1, 0]:
        for a, b in [(P, P), (N, N), (P, N)]:
            v.append((4, a, b, acc & M))                       # macc wrap at both ends
    for x in [0, 127, 128, -128, -129, 255, 256, -1, (1 << 31) - 1, -(1 << 31)]:
        for sh in [0, 1, 2, 7, 8, 31, 32, 62, 63]:
            v.append((5, x & M, sh | (0xABCDEF << 6), 0))      # rqs, junk in rs2[63:6]
    for sh in [1, 2, 8, 62, 63]:                               # half-way rounding points
        for x in [(1 << (sh - 1)), -(1 << (sh - 1)), (3 << (sh - 1)), -(3 << (sh - 1))]:
            v.append((5, x & M, sh, 0))
    for op in ILLEGAL:
        v.append((op, P, P, 0))
    return v


def rqs_overflow_vectors():
    """rs1 near INT64_MAX so that rs1 + 2^(sh-1) leaves the signed 64-bit range."""
    v = []
    for sh in [1, 2, 8, 32, 63]:
        for d in [0, 1]:
            v.append((5, ((1 << 63) - 1 - d) & MASK64, sh, 0))
    return v


# --------------------------------------------------------------------- APB / RAL
class ApbRawSeq(uvm_sequence):
    """Raw APB transfers (bypassing RAL); results land in self.items."""

    def __init__(self, name="apb_raw_seq", ops=()):
        super().__init__(name)
        self.ops = list(ops)        # (write, addr, data)
        self.items = []

    async def body(self):
        for w, a, d in self.ops:
            it = ApbItem("apb", addr=a, write=w, data=d)
            await self.start_item(it)
            await self.finish_item(it)
            self.items.append(it)
