"""Reference model for MLACC: the Vortex-V Xmlacc golden model plus MLACC wrapping.

`xmlacc_model.py` is copied verbatim from Vortex-V (model/xmlacc_model.py) so the
scoreboard checks the RTL against an oracle written independently of it.
"""
from mlacc_tb import xmlacc_model as xm

MASK64 = (1 << 64) - 1
OPS = {0: "dot8", 1: "dot8u", 2: "dot8su", 4: "macc", 5: "rqs"}
ILLEGAL_OPS = (3, 6, 7)


def expected(op, rs1, rs2, rs3):
    """Return (result_u64, sat) that MLACC must produce for one command."""
    if op == 0:
        r, s = xm.dot8(rs1, rs2), False
    elif op == 1:
        r, s = xm.dot8u(rs1, rs2), False
    elif op == 2:
        r, s = xm.dot8su(rs1, rs2), False
    elif op == 4:
        r, s = xm.macc(rs1, rs2, rs3), False
    elif op == 5:
        r, s = xm.rqs(rs1, rs2)
    else:
        r, s = 0, False   # illegal op: result 0, IRQ_STATUS.ERR set
    return int(r) & MASK64, int(bool(s))
