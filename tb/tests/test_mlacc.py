"""MLACC UVM tests. Each class is a cocotb test via @pyuvm.test(); select one with
make -C sim TEST=test_mlacc UVM_TEST=<name>."""
import random

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from pyuvm import uvm_test, ConfigDB, uvm_root, uvm_status_e

from mlacc_tb.cfg import MlaccCfg
from mlacc_tb.env import MlaccEnv
from mlacc_tb.ral import REG_SPEC, UNMAPPED_PROBES
from mlacc_tb.seqs import (RandCmdSeq, DirectedCmdSeq, TrafficProfile, ApbRawSeq,
                           corner_vectors, rqs_overflow_vectors, lanes)

P8 = lanes([0x7F] * 8)


class MlaccBaseTest(uvm_test):
    """Builds the env, brings the DUT out of reset, enables it, runs body(), drains."""
    drain_timeout = 5000

    def build_phase(self):
        self.cfg = MlaccCfg(cocotb.top)
        self.configure(self.cfg)
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = MlaccEnv("env", self)
        self.reg_errors = []

    def configure(self, cfg):
        """Override to set knobs."""

    def end_of_elaboration_phase(self):
        self.regs = self.env.regs

    async def run_phase(self):
        self.raise_objection()
        await self.cfg.start_clock()
        await self.cfg.reset()
        await self.reg_write("CTRL", 0x1)
        await self.body()
        await self.drain()
        self.drop_objection()

    async def body(self):
        pass

    # ---------------------------------------------------------------- helpers
    async def reg_write(self, name, value):
        status = await self.regs.regs[name].write(value)
        if status != uvm_status_e.UVM_IS_OK:
            self.reg_errors.append(f"write {name} returned {status}")

    async def reg_read(self, name, check=True):
        """Frontdoor read; for non-volatile registers also check against the RAL mirror."""
        rg = self.regs.regs[name]
        exp = None if rg.is_volatile() else rg.get_mirrored_value()
        status, val = await rg.read()
        if status != uvm_status_e.UVM_IS_OK:
            self.reg_errors.append(f"read {name} returned {status}")
        if check and exp is not None and val != exp:
            self.reg_errors.append(f"RAL mirror mismatch {name}: read 0x{val:08x}, mirror 0x{exp:08x}")
        return val

    async def run_cmds(self, seq):
        await seq.start(self.env.cmd.sequencer)

    async def drain(self):
        dut, sb = self.cfg.dut, self.env.scoreboard
        for _ in range(self.drain_timeout):
            if not sb.pending and not int(dut.rsp_valid.value) and not int(dut.s1_valid.value) \
                    and not int(dut.cmd_valid.value):
                break
            await RisingEdge(dut.clk)
        await self.cfg.clocks(3)

    def check_phase(self):
        if self.reg_errors:
            raise AssertionError(f"{len(self.reg_errors)} register check error(s); first: {self.reg_errors[0]}")


# =========================================================================== tests
@pyuvm.test()
class smoke_test(MlaccBaseTest):
    """One of every op plus 50 random commands, no stalls."""

    def configure(self, cfg):
        cfg.cmd_idle_prob, cfg.rsp_stall_prob = 0.0, 0.0

    async def body(self):
        await self.run_cmds(DirectedCmdSeq(vectors=[
            (0, 0x0102030405060708, 0x0101010101010101, 0),
            (1, 2**64 - 1, 2**64 - 1, 0),
            (2, 0x80808080808080FF, 0xFF00FF00FF00FF00, 0),
            (4, P8, P8, 5),
            (5, 1 << 20, 4, 0)]))
        await self.run_cmds(RandCmdSeq(n=50))


@pyuvm.test()
class reg_test(MlaccBaseTest):
    """RAL: reset values, RW bit-bash, RO write-ignore, unmapped PSLVERR, W1C semantics."""

    async def run_phase(self):
        self.raise_objection()
        await self.cfg.start_clock()
        await self.cfg.reset()
        # 1. reset values of every register (CTRL still 0)
        for name, _off, fields in REG_SPEC:
            val = await self.reg_read(name)
            want = sum(r << lsb for _f, lsb, _s, _a, _v, r in fields)
            if val != want:
                self.reg_errors.append(f"reset value {name}=0x{val:08x}, spec 0x{want:08x}")
        # 2. bit-bash RW registers: walking 1, walking 0, all-ones, all-zeros
        for name, mask in (("SCRATCH", 0xFFFFFFFF), ("CTRL", 0x0000000E)):  # keep EN=0 in CTRL
            pats = [1 << i for i in range(32)] + [~(1 << i) & 0xFFFFFFFF for i in range(32)] \
                + [0xFFFFFFFF, 0, 0xA5A5A5A5, 0x5A5A5A5A]
            for p in pats:
                await self.reg_write(name, p & mask if name == "CTRL" else p)
                await self.reg_read(name)
        # 3. RO registers ignore writes (raw APB: the RAL itself refuses RO writes)
        ro = ["ID", "VERSION", "STATUS", "CMD_COUNT", "RSP_COUNT"]
        raw = ApbRawSeq(ops=[(True, self.regs.addr_of(n), 0xFFFFFFFF) for n in ro])
        await raw.start(self.env.apb.sequencer)
        for name in ro:
            await self.reg_read(name)
        # 4. unmapped addresses: PSLVERR, read 0 (checked by the cycle model)
        raw = ApbRawSeq(ops=[(w, a, 0xDEADBEEF) for a in UNMAPPED_PROBES for w in (True, False)])
        await raw.start(self.env.apb.sequencer)
        for it in raw.items:
            if not it.slverr:
                self.reg_errors.append(f"no PSLVERR at unmapped 0x{it.addr:03x}")
        # 5. W1C: produce SAT, then check write-0 keeps it and write-1 clears it
        await self.reg_write("CTRL", 0x1)
        await self.run_cmds(DirectedCmdSeq(vectors=[(5, 1000, 0, 0)]))      # clamps -> SAT
        await self.drain()
        if await self.reg_read("MLSTAT") != 1:
            self.reg_errors.append("MLSTAT.SAT not set by a clamping rqs")
        await self.reg_write("MLSTAT", 0)
        if await self.reg_read("MLSTAT") != 1:
            self.reg_errors.append("MLSTAT.SAT cleared by writing 0 (must be W1C)")
        await self.reg_write("MLSTAT", 1)
        if await self.reg_read("MLSTAT") != 0:
            self.reg_errors.append("MLSTAT.SAT not cleared by writing 1")
        sts = await self.reg_read("IRQ_STATUS")
        if sts != 0b011:
            self.reg_errors.append(f"IRQ_STATUS=0b{sts:03b}, expected DONE|SAT")
        await self.reg_write("IRQ_STATUS", 0b001)
        if await self.reg_read("IRQ_STATUS") != 0b010:
            self.reg_errors.append("IRQ_STATUS W1C of DONE failed")
        await self.reg_write("IRQ_STATUS", 0b111)
        if await self.reg_read("CMD_COUNT") != 1 or await self.reg_read("RSP_COUNT") != 1:
            self.reg_errors.append("CMD/RSP_COUNT != 1 after one command")
        self.drop_objection()


@pyuvm.test()
class random_test(MlaccBaseTest):
    """Balanced constrained-random traffic with light backpressure and idle gaps."""
    N = 2000

    def configure(self, cfg):
        cfg.cmd_idle_prob, cfg.rsp_stall_prob, cfg.rsp_stall_burst = 0.2, 0.15, (1, 4)

    async def body(self):
        await self.run_cmds(RandCmdSeq(n=self.N))


@pyuvm.test()
class rqs_overflow_test(MlaccBaseTest):
    """Regression for VTX-RQS-001 (fixed in Vortex-V PR #2): rqs inputs within
    2^(sh-1) of INT64_MAX, checked with the waiver OFF."""

    def configure(self, cfg):
        cfg.waive_known_issues = False

    async def body(self):
        await self.run_cmds(DirectedCmdSeq(vectors=rqs_overflow_vectors()))


@pyuvm.test()
class corner_test(MlaccBaseTest):
    """Directed spec corners: lane extremes for every op, macc wrap at both ends,
    rqs at every shift boundary and every rounding half-way point, illegal ops."""

    def configure(self, cfg):
        cfg.cmd_idle_prob, cfg.rsp_stall_prob = 0.0, 0.3

    async def body(self):
        await self.run_cmds(DirectedCmdSeq(vectors=corner_vectors() + rqs_overflow_vectors()))


@pyuvm.test()
class stress_test(MlaccBaseTest):
    """Back-to-back commands into heavy, bursty backpressure: keeps the FIFO full."""

    def configure(self, cfg):
        cfg.cmd_idle_prob, cfg.rsp_stall_prob, cfg.rsp_stall_burst = 0.0, 0.5, (1, 8)

    async def body(self):
        await self.run_cmds(RandCmdSeq(n=3000))


@pyuvm.test()
class irq_test(MlaccBaseTest):
    """Every interrupt source with its enable on and off; W1C clears drop the line."""

    def configure(self, cfg):
        cfg.cmd_idle_prob, cfg.rsp_stall_prob = 0.0, 0.0

    async def body(self):
        triggers = {0: (0, P8, P8, 0),        # DONE: any command
                    1: (5, 5000, 2, 0),       # SAT: clamping rqs
                    2: (6, 1, 1, 0)}          # ERR: illegal op
        for bit, vec in triggers.items():
            for enabled in (False, True):
                await self.reg_write("IRQ_STATUS", 0b111)
                await self.reg_write("CTRL", 0x1 | ((1 << (bit + 1)) if enabled else 0))
                await self.run_cmds(DirectedCmdSeq(vectors=[vec]))
                await self.drain()
                if int(self.cfg.dut.irq.value) != int(enabled):
                    self.reg_errors.append(f"irq={int(self.cfg.dut.irq.value)} for source {bit} "
                                           f"enabled={enabled}")
                await self.reg_write("IRQ_STATUS", 0b111)
                await self.cfg.clocks(1)
                if int(self.cfg.dut.irq.value):
                    self.reg_errors.append(f"irq stuck after W1C of source {bit}")
        await self.reg_write("CTRL", 0xF)                 # all enables, all sources at once
        await self.run_cmds(DirectedCmdSeq(vectors=list(triggers.values())))


@pyuvm.test()
class csr_traffic_test(MlaccBaseTest):
    """Virtual sequence: random traffic while a CSR thread concurrently polls
    registers, W1C-clears status bits and toggles CTRL.EN (incl. while busy)."""

    def configure(self, cfg):
        cfg.cmd_idle_prob, cfg.rsp_stall_prob, cfg.rsp_stall_burst = 0.1, 0.3, (1, 6)

    async def body(self):
        prof = TrafficProfile(op_w={"dot8": 10, "dot8u": 5, "dot8su": 5, "macc": 10,
                                    "rqs": 50, "illegal": 20},
                              rqs_val_w={"int32": 20, "int8ish": 5, "big": 60, "near_max": 5,
                                         "random": 10})
        traffic = cocotb.start_soon(self.run_cmds(RandCmdSeq(n=1500, profile=prof)))
        names = [n for n, _o, _f in REG_SPEC]
        while not traffic.done():
            r = random.random()
            if r < 0.45:
                await self.reg_read(random.choice(names))
            elif r < 0.75:
                await self.reg_write("IRQ_STATUS", random.choice([1, 2, 4, 7]))
            elif r < 0.85:
                await self.reg_write("MLSTAT", 1)
            elif r < 0.95:
                await self.reg_write("SCRATCH", random.getrandbits(32))
            else:
                await self.reg_write("CTRL", random.choice([0x0, 0xE]))   # disable (maybe busy)
                await self.cfg.clocks(random.randint(1, 20))
                await self.reg_write("CTRL", random.choice([0x1, 0xF]))
        await traffic


@pyuvm.test()
class reset_midflight_test(MlaccBaseTest):
    """Fill the pipeline and FIFO, assert reset with results still inside, then check
    everything restarts from reset values and new traffic is clean."""

    def configure(self, cfg):
        cfg.cmd_idle_prob = 0.0

    async def body(self):
        for _round in range(3):
            self.cfg.rsp_stall_prob, self.cfg.rsp_stall_burst = 1.0, (1000, 1000)
            await self.run_cmds(RandCmdSeq(n=4))          # credit allows exactly 4 in flight
            await self.cfg.clocks(3)
            if int(self.cfg.dut.u_fifo.count.value) != 4:
                self.reg_errors.append("FIFO not full before mid-flight reset")
            await self.cfg.reset(cycles=3)
            self.regs.reset()                             # RAL mirror follows the hardware reset
            for name in ("STATUS", "CMD_COUNT", "RSP_COUNT", "IRQ_STATUS", "CTRL"):
                if await self.reg_read(name) != 0:
                    self.reg_errors.append(f"{name} not 0 after mid-flight reset")
            self.cfg.rsp_stall_prob, self.cfg.rsp_stall_burst = 0.2, (1, 3)
            await self.reg_write("CTRL", 0x1)
            await self.run_cmds(RandCmdSeq(n=100))
            await self.drain()
