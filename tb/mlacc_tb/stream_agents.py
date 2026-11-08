"""Command (active) and result (reactive) valid/ready stream agents, plus a
per-cycle signal monitor used by the IRQ check, protocol checkers and coverage."""
import random
from dataclasses import dataclass

from cocotb.triggers import RisingEdge, FallingEdge
from pyuvm import (uvm_sequence_item, uvm_driver, uvm_monitor, uvm_agent,
                   uvm_sequencer, uvm_analysis_port, uvm_component, ConfigDB)

from mlacc_tb.ref_model import OPS

MASK64 = (1 << 64) - 1


# --------------------------------------------------------------------------- items
class CmdItem(uvm_sequence_item):
    def __init__(self, name="cmd_item", tag=0, op=0, rs1=0, rs2=0, rs3=0):
        super().__init__(name)
        self.tag, self.op = tag, op
        self.rs1, self.rs2, self.rs3 = rs1 & MASK64, rs2 & MASK64, rs3 & MASK64
        self.cycle = 0

    def __str__(self):
        return (f"CMD tag={self.tag:3d} {OPS.get(self.op, f'ILLEGAL{self.op}'):7s} "
                f"rs1=0x{self.rs1:016x} rs2=0x{self.rs2:016x} rs3=0x{self.rs3:016x} [cyc {self.cycle}]")


class RspItem(uvm_sequence_item):
    def __init__(self, name="rsp_item", tag=0, result=0, sat=0):
        super().__init__(name)
        self.tag, self.result, self.sat = tag, result, sat
        self.cycle = 0

    def __str__(self):
        return f"RSP tag={self.tag:3d} result=0x{self.result:016x} sat={self.sat} [cyc {self.cycle}]"


@dataclass
class ResetEvent:
    """Published by SignalMonitor when rst_n is asserted after having been released."""
    cycle: int


@dataclass
class CycleSnapshot:
    """Everything visible on the DUT pins (plus two white-box probes) in one cycle."""
    cycle: int
    cmd_valid: int
    cmd_ready: int
    cmd_payload: tuple
    rsp_valid: int
    rsp_ready: int
    rsp_payload: tuple
    irq: int
    psel: int
    penable: int
    apb_payload: tuple     # (pwrite, paddr, pwdata)
    prdata: int
    pslverr: int
    fifo_count: int        # white-box: result FIFO occupancy
    s1_valid: int          # white-box: pipeline stage-1 valid
    irq_sts: int           # white-box: IRQ_STATUS register
    irq_en: int            # white-box: CTRL[3:1] interrupt enables
    ev_sat: int            # white-box: SAT event this cycle
    ev_err: int            # white-box: illegal-op event this cycle


# --------------------------------------------------------------------------- command agent
class CmdDriver(uvm_driver):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")

    def _drive(self, item):
        d = self.cfg.dut
        d.cmd_valid.value = 1
        d.cmd_tag.value, d.cmd_op.value = item.tag, item.op
        d.cmd_rs1.value, d.cmd_rs2.value, d.cmd_rs3.value = item.rs1, item.rs2, item.rs3

    async def run_phase(self):
        d = self.cfg.dut
        await self.cfg.wait_reset()
        item = None
        while True:
            if item is None:
                d.cmd_valid.value = 0
                item = await self.seq_item_port.get_next_item()
                await RisingEdge(d.clk)
            while random.random() < self.cfg.cmd_idle_prob:      # random idle gaps
                d.cmd_valid.value = 0
                await RisingEdge(d.clk)
            self._drive(item)
            while True:                                          # hold until accepted
                await FallingEdge(d.clk)
                fire = int(d.cmd_ready.value)
                await RisingEdge(d.clk)
                if fire:
                    break
            self.seq_item_port.item_done()
            ok, item = self.seq_item_port.try_next_item()       # back-to-back if available
            if not ok:
                item = None


class CmdMonitor(uvm_monitor):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        d = self.cfg.dut
        while True:
            await FallingEdge(d.clk)
            if int(d.rst_n.value) and int(d.cmd_valid.value) and int(d.cmd_ready.value):
                tr = CmdItem("cmd_mon", int(d.cmd_tag.value), int(d.cmd_op.value),
                             int(d.cmd_rs1.value), int(d.cmd_rs2.value), int(d.cmd_rs3.value))
                tr.cycle = self.cfg.cycle
                self.ap.write(tr)


class CmdAgent(uvm_agent):
    def build_phase(self):
        super().build_phase()
        self.monitor = CmdMonitor("monitor", self)
        if self.active():
            self.sequencer = uvm_sequencer("sequencer", self)
            self.driver = CmdDriver("driver", self)

    def connect_phase(self):
        if self.active():
            self.driver.seq_item_port.connect(self.sequencer.seq_item_export)


# --------------------------------------------------------------------------- result agent
class RspResponder(uvm_component):
    """Reactive slave: drives rsp_ready with configurable random stall bursts."""

    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")

    async def run_phase(self):
        d = self.cfg.dut
        await self.cfg.wait_reset()
        stall_left = 0
        while True:
            if stall_left == 0 and random.random() < self.cfg.rsp_stall_prob:
                stall_left = random.randint(*self.cfg.rsp_stall_burst)
            if stall_left:
                d.rsp_ready.value = 0
                stall_left -= 1
            else:
                d.rsp_ready.value = 1
            await RisingEdge(d.clk)


class RspMonitor(uvm_monitor):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        d = self.cfg.dut
        while True:
            await FallingEdge(d.clk)
            if int(d.rst_n.value) and int(d.rsp_valid.value) and int(d.rsp_ready.value):
                tr = RspItem("rsp_mon", int(d.rsp_tag.value), int(d.rsp_result.value),
                             int(d.rsp_sat.value))
                tr.cycle = self.cfg.cycle
                self.ap.write(tr)


class RspAgent(uvm_agent):
    def build_phase(self):
        super().build_phase()
        self.monitor = RspMonitor("monitor", self)
        if self.active():
            self.responder = RspResponder("responder", self)


# --------------------------------------------------------------------------- signal monitor
class SignalMonitor(uvm_monitor):
    """Publishes a CycleSnapshot every clock after reset (IRQ, handshakes, probes)."""

    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        d = self.cfg.dut
        in_reset = True
        while True:
            await FallingEdge(d.clk)
            if not int(d.rst_n.value):
                if not in_reset:
                    self.ap.write(ResetEvent(self.cfg.cycle))
                in_reset = True
                continue
            in_reset = False
            self.ap.write(CycleSnapshot(
                cycle=self.cfg.cycle,
                cmd_valid=int(d.cmd_valid.value), cmd_ready=int(d.cmd_ready.value),
                cmd_payload=(int(d.cmd_tag.value), int(d.cmd_op.value), int(d.cmd_rs1.value),
                             int(d.cmd_rs2.value), int(d.cmd_rs3.value)),
                rsp_valid=int(d.rsp_valid.value), rsp_ready=int(d.rsp_ready.value),
                rsp_payload=(int(d.rsp_tag.value), int(d.rsp_result.value), int(d.rsp_sat.value))
                if int(d.rsp_valid.value) else (),
                irq=int(d.irq.value),
                psel=int(d.psel.value), penable=int(d.penable.value),
                apb_payload=(int(d.pwrite.value), int(d.paddr.value), int(d.pwdata.value)),
                prdata=int(d.prdata.value), pslverr=int(d.pslverr.value),
                fifo_count=int(d.u_fifo.count.value),
                s1_valid=int(d.s1_valid.value),
                irq_sts=int(d.u_csr.irq_sts_q.value),
                irq_en=(int(d.u_csr.ctrl_q.value) >> 1) & 7,
                ev_sat=int(d.u_csr.ev_sat.value), ev_err=int(d.u_csr.ev_err.value),
            ))
