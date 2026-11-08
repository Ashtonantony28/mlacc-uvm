"""Checkers: a transaction-level data scoreboard and a cycle-accurate CSR/IRQ/
flow-control reference model.

* MlaccScoreboard  — every accepted command must come back exactly once, in
  order, with the tag, result and sat flag the Vortex-V golden model predicts.
* MlaccCycleModel  — replays the MLACC spec cycle by cycle from the pin-level
  CycleSnapshot stream and checks APB read data, PSLVERR, IRQ, cmd_ready and
  the FIFO / stage-1 occupancy against it.
"""
from collections import deque

from pyuvm import uvm_component, uvm_subscriber, ConfigDB

from mlacc_tb.ref_model import expected, ILLEGAL_OPS
from mlacc_tb.stream_agents import ResetEvent

A_ID, A_VERSION, A_CTRL, A_STATUS = 0x000, 0x004, 0x008, 0x00C
A_MLSTAT, A_IRQ_STATUS, A_CMD_COUNT, A_RSP_COUNT, A_SCRATCH = 0x010, 0x014, 0x018, 0x01C, 0x020
MAPPED = {A_ID, A_VERSION, A_CTRL, A_STATUS, A_MLSTAT, A_IRQ_STATUS, A_CMD_COUNT, A_RSP_COUNT, A_SCRATCH}
FIFO_DEPTH = 4
MAX_ERRORS_LOGGED = 20


def known_issue(cmd):
    """Return the id of a documented, root-caused RTL-vs-golden-model discrepancy, or None.

    VTX-RQS-001: Vortex-V's vortex_xmlacc computes rqs `rs1 + 2^(sh-1)` in 64 bits,
    which wraps when the sum exceeds INT64_MAX; the golden model adds in unbounded
    precision. Found by random_test/smoke_test on the first run (2026-11-08).
    """
    if cmd.op == 5:
        sh = cmd.rs2 & 63
        x = cmd.rs1 - (1 << 64) if cmd.rs1 >> 63 else cmd.rs1
        if sh and x + (1 << (sh - 1)) > (1 << 63) - 1:
            return "VTX-RQS-001"
    return None


class _Tap(uvm_subscriber):
    """Forwards analysis writes to a callback (lets one component own several imps)."""

    def __init__(self, name, parent, cb):
        super().__init__(name, parent)
        self._cb = cb

    def write(self, tr):
        self._cb(tr)


class _Checker(uvm_component):
    def __init__(self, name, parent):
        super().__init__(name, parent)
        self.errors = []

    def fail(self, msg):
        self.errors.append(msg)
        if len(self.errors) <= MAX_ERRORS_LOGGED:
            self.logger.error(msg)

    def check_phase(self):
        if self.errors:
            raise AssertionError(f"{self.get_full_name()}: {len(self.errors)} error(s); first: {self.errors[0]}")


class MlaccScoreboard(_Checker):
    def build_phase(self):
        self.cmd_tap = _Tap("cmd_tap", self, self.on_cmd)
        self.rsp_tap = _Tap("rsp_tap", self, self.on_rsp)
        self.sig_tap = _Tap("sig_tap", self, self.on_sig)
        self.pending = deque()
        self.n_checked = 0
        self.n_cmds = 0
        self.allow_pending_at_end = False
        self.waive_known = ConfigDB().get(self, "", "cfg").waive_known_issues
        self.waived = {}

    def on_sig(self, tr):
        if isinstance(tr, ResetEvent):
            self.logger.info(f"reset at cycle {tr.cycle}: dropping {len(self.pending)} in-flight command(s)")
            self.pending.clear()

    def on_cmd(self, cmd):
        res, sat = expected(cmd.op, cmd.rs1, cmd.rs2, cmd.rs3)
        self.pending.append((cmd, res, sat))
        self.n_cmds += 1

    def on_rsp(self, rsp):
        if not self.pending:
            self.fail(f"unexpected result with nothing in flight: {rsp}")
            return
        cmd, res, sat = self.pending.popleft()
        if (rsp.tag, rsp.result, rsp.sat) != (cmd.tag, res, sat):
            kid = known_issue(cmd)
            if kid and self.waive_known and rsp.tag == cmd.tag:
                self.waived[kid] = self.waived.get(kid, 0) + 1
                self.n_checked += 1
                return
            self.fail(f"MISMATCH for {cmd}\n   got  {rsp}\n   want tag={cmd.tag} "
                      f"result=0x{res:016x} sat={sat}")
        self.n_checked += 1

    def check_phase(self):
        if self.pending and not self.allow_pending_at_end:
            self.fail(f"{len(self.pending)} command(s) never returned; first: {self.pending[0][0]}")
        super().check_phase()

    def report_phase(self):
        self.logger.info(f"scoreboard: {self.n_checked} results checked, {len(self.errors)} errors")
        for kid, n in self.waived.items():
            self.logger.warning(f"scoreboard: {n} mismatch(es) waived as known issue {kid} "
                                f"(see docs/KNOWN-ISSUES.md)")


class MlaccCycleModel(_Checker):
    """Cycle-accurate model of the CSR block, IRQ and flow control (spec §3)."""

    def build_phase(self):
        self.sig_tap = _Tap("sig_tap", self, self.on_cycle)
        self.reset_state()
        self.n_cycles = 0
        self.n_reads_checked = 0

    def reset_state(self):
        self.ctrl = self.scratch = self.cmd_cnt = self.rsp_cnt = 0
        self.mlstat = 0
        self.irq_sts = 0
        self.s1 = None          # (sat, illegal) of the command in stage 1, or None
        self.fifo = 0

    # ---- spec functions ----
    def irq(self):
        en = self.ctrl >> 1
        return int(bool(self.irq_sts & en & 0x7))

    def cmd_ready(self):
        return int(bool(self.ctrl & 1) and (self.fifo + (self.s1 is not None)) < FIFO_DEPTH)

    def read(self, addr):
        busy = int(self.s1 is not None or self.fifo > 0)
        return {A_ID: 0x4D4C4143, A_VERSION: 0x00010000, A_CTRL: self.ctrl,
                A_STATUS: (self.fifo << 4) | busy, A_MLSTAT: self.mlstat,
                A_IRQ_STATUS: self.irq_sts, A_CMD_COUNT: self.cmd_cnt,
                A_RSP_COUNT: self.rsp_cnt, A_SCRATCH: self.scratch}.get(addr, 0)

    # ---- per-cycle step ----
    def on_cycle(self, s):
        if isinstance(s, ResetEvent):
            self.reset_state()
            return
        self.n_cycles += 1
        c = s.cycle
        # 1. check DUT outputs against the current model state
        if s.irq != self.irq():
            self.fail(f"[cyc {c}] irq={s.irq}, model expects {self.irq()} "
                      f"(IRQ_STATUS=0b{self.irq_sts:03b} CTRL=0x{self.ctrl:x})")
        if s.cmd_ready != self.cmd_ready():
            self.fail(f"[cyc {c}] cmd_ready={s.cmd_ready}, model expects {self.cmd_ready()} "
                      f"(fifo={self.fifo} s1={self.s1 is not None} EN={self.ctrl & 1})")
        if s.fifo_count != self.fifo or s.s1_valid != int(self.s1 is not None):
            self.fail(f"[cyc {c}] occupancy fifo={s.fifo_count}/s1={s.s1_valid}, model "
                      f"fifo={self.fifo}/s1={int(self.s1 is not None)}")
        apb = s.psel and s.penable
        pwrite, paddr, pwdata = s.apb_payload
        if apb:
            exp_err = int(paddr not in MAPPED)
            if s.pslverr != exp_err:
                self.fail(f"[cyc {c}] PSLVERR={s.pslverr} at 0x{paddr:03x}, expected {exp_err}")
            if not pwrite:
                self.n_reads_checked += 1
                exp = self.read(paddr)
                if s.prdata != exp:
                    self.fail(f"[cyc {c}] APB read 0x{paddr:03x} = 0x{s.prdata:08x}, model 0x{exp:08x}")

        # 2. compute next state (software clears first, hardware sets win)
        cmd_fire = s.cmd_valid and s.cmd_ready
        rsp_fire = s.rsp_valid and s.rsp_ready
        if apb and pwrite:
            if paddr == A_CTRL:
                self.ctrl = pwdata & 0xF
            elif paddr == A_SCRATCH:
                self.scratch = pwdata
            elif paddr == A_MLSTAT and (pwdata & 1):
                self.mlstat = 0
            elif paddr == A_IRQ_STATUS:
                self.irq_sts &= ~pwdata & 0x7
        if self.s1 is not None:
            sat, illegal = self.s1
            if sat:
                self.mlstat = 1
                self.irq_sts |= 0b010
            if illegal:
                self.irq_sts |= 0b100
            self.fifo += 1
        if rsp_fire:
            self.irq_sts |= 0b001
            self.rsp_cnt = (self.rsp_cnt + 1) & 0xFFFFFFFF
            self.fifo -= 1
        if cmd_fire:
            self.cmd_cnt = (self.cmd_cnt + 1) & 0xFFFFFFFF
            _tag, op, rs1, rs2, rs3 = s.cmd_payload
            _res, sat = expected(op, rs1, rs2, rs3)
            self.s1 = (sat, op in ILLEGAL_OPS)
        else:
            self.s1 = None

    def report_phase(self):
        self.logger.info(f"cycle model: {self.n_cycles} cycles, {self.n_reads_checked} APB reads "
                         f"checked, {len(self.errors)} errors")
