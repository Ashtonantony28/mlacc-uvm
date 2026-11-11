"""Environment configuration object and the shared clock/cycle service."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge


class MlaccCfg:
    """Holds the DUT handle and the knobs every component reads from ConfigDB.

    Timing convention used by every agent:
      * drivers change DUT inputs right after a rising edge;
      * monitors and drivers *sample* on the falling edge, when every input and
        combinational output is stable for the next rising edge;
      * `cycle` counts rising edges, so an event sampled at a falling edge with
        stamp c takes effect at rising edge c + 1.
    """

    def __init__(self, dut):
        self.dut = dut
        self.cycle = 0
        # stimulus knobs (tests override these)
        self.cmd_idle_prob = 0.2        # chance of an idle cycle between commands
        self.rsp_stall_prob = 0.0       # chance rsp_ready is low in a cycle
        self.rsp_stall_burst = (1, 1)   # stall burst length range when stalling
        self.coverage_enabled = True
        self.waive_known_issues = False  # VTX-RQS-001 fixed upstream; see scoreboard.known_issue / docs/KNOWN-ISSUES.md
        self.reset_done = False

    async def start_clock(self, period_ns=10):
        cocotb.start_soon(Clock(self.dut.clk, period_ns, unit="ns").start())
        cocotb.start_soon(self._count_cycles())

    async def _count_cycles(self):
        while True:
            await RisingEdge(self.dut.clk)
            self.cycle += 1

    async def reset(self, cycles=5):
        dut = self.dut
        self.reset_done = False
        dut.rst_n.value = 0
        for name in ("psel", "penable", "pwrite", "paddr", "pwdata", "cmd_valid",
                     "cmd_tag", "cmd_op", "cmd_rs1", "cmd_rs2", "cmd_rs3"):
            getattr(dut, name).value = 0
        dut.rsp_ready.value = 0
        for _ in range(cycles):
            await RisingEdge(dut.clk)
        dut.rst_n.value = 1
        await FallingEdge(dut.clk)
        self.reset_done = True

    async def wait_reset(self):
        while not self.reset_done:
            await FallingEdge(self.dut.clk)

    async def clocks(self, n=1):
        for _ in range(n):
            await RisingEdge(self.dut.clk)
