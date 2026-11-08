"""APB3 master agent: sequence item, driver, monitor, agent."""
from cocotb.triggers import RisingEdge, FallingEdge
from pyuvm import (uvm_sequence_item, uvm_driver, uvm_monitor, uvm_agent,
                   uvm_sequencer, uvm_analysis_port, ConfigDB, uvm_active_passive_enum)


class ApbItem(uvm_sequence_item):
    def __init__(self, name="apb_item", addr=0, write=False, data=0):
        super().__init__(name)
        self.addr = addr
        self.write = write
        self.data = data          # write data, or read data after the access
        self.slverr = False
        self.cycle = 0            # stamp of the access phase (monitor)

    def __str__(self):
        k = "WR" if self.write else "RD"
        e = " SLVERR" if self.slverr else ""
        return f"APB {k} @0x{self.addr:03x} = 0x{self.data:08x}{e} [cyc {self.cycle}]"

    def do_copy(self, rhs):
        super().do_copy(rhs)
        self.addr, self.write, self.data, self.slverr = rhs.addr, rhs.write, rhs.data, rhs.slverr


class ApbDriver(uvm_driver):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")

    async def run_phase(self):
        dut = self.cfg.dut
        await self.cfg.wait_reset()
        while True:
            item = await self.seq_item_port.get_next_item()
            await RisingEdge(dut.clk)
            # setup phase
            dut.psel.value, dut.penable.value = 1, 0
            dut.pwrite.value = int(item.write)
            dut.paddr.value = item.addr
            dut.pwdata.value = item.data if item.write else 0
            await RisingEdge(dut.clk)
            # access phase; wait states honoured via PREADY
            dut.penable.value = 1
            while True:
                await FallingEdge(dut.clk)
                if int(dut.pready.value):
                    break
            if not item.write:
                item.data = int(dut.prdata.value)
            item.slverr = bool(int(dut.pslverr.value))
            await RisingEdge(dut.clk)
            dut.psel.value, dut.penable.value = 0, 0
            self.seq_item_port.item_done()


class ApbMonitor(uvm_monitor):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        dut = self.cfg.dut
        while True:
            await FallingEdge(dut.clk)
            if not int(dut.rst_n.value):
                continue
            if int(dut.psel.value) and int(dut.penable.value) and int(dut.pready.value):
                tr = ApbItem("apb_mon", addr=int(dut.paddr.value), write=bool(int(dut.pwrite.value)))
                tr.data = int(dut.pwdata.value) if tr.write else int(dut.prdata.value)
                tr.slverr = bool(int(dut.pslverr.value))
                tr.cycle = self.cfg.cycle
                self.ap.write(tr)


class ApbAgent(uvm_agent):
    def build_phase(self):
        super().build_phase()
        self.monitor = ApbMonitor("monitor", self)
        if self.get_is_active() == uvm_active_passive_enum.UVM_ACTIVE:
            self.sequencer = uvm_sequencer("sequencer", self)
            self.driver = ApbDriver("driver", self)

    def connect_phase(self):
        if self.get_is_active() == uvm_active_passive_enum.UVM_ACTIVE:
            self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
