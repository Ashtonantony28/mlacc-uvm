"""M0 smoke: one command of each op round-trips through MLACC (plain cocotb)."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

from mlacc_tb.ref_model import expected


async def apb_write(dut, addr, data):
    dut.psel.value, dut.penable.value, dut.pwrite.value = 1, 0, 1
    dut.paddr.value, dut.pwdata.value = addr, data
    await RisingEdge(dut.clk)
    dut.penable.value = 1
    await RisingEdge(dut.clk)
    dut.psel.value, dut.penable.value = 0, 0


@cocotb.test()
async def smoke(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for s in ("psel", "penable", "pwrite", "paddr", "pwdata", "cmd_valid",
              "cmd_tag", "cmd_op", "cmd_rs1", "cmd_rs2", "cmd_rs3"):
        getattr(dut, s).value = 0
    dut.rsp_ready.value = 1
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await apb_write(dut, 0x008, 1)          # CTRL.EN

    vecs = [(0, 0x0102030405060708, 0x0101010101010101, 0),
            (1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0),
            (2, 0x80808080808080FF, 0xFF00FF00FF00FF00, 0),
            (4, 0x7F7F7F7F7F7F7F7F, 0x7F7F7F7F7F7F7F7F, 5),
            (5, 1 << 20, 4, 0)]
    for tag, (op, a, b, c) in enumerate(vecs):
        dut.cmd_valid.value, dut.cmd_tag.value, dut.cmd_op.value = 1, tag, op
        dut.cmd_rs1.value, dut.cmd_rs2.value, dut.cmd_rs3.value = a, b, c
        await RisingEdge(dut.clk)
        while not dut.cmd_ready.value:
            await RisingEdge(dut.clk)
        dut.cmd_valid.value = 0
        while True:
            await ReadOnly()
            if dut.rsp_valid.value:
                break
            await RisingEdge(dut.clk)
        res, sat = expected(op, a, b, c)
        assert int(dut.rsp_tag.value) == tag
        assert int(dut.rsp_result.value) == res, f"op{op}: {int(dut.rsp_result.value):#x} != {res:#x}"
        assert int(dut.rsp_sat.value) == sat
        await RisingEdge(dut.clk)
