"""Register abstraction layer (RAL) for MLACC: register model, APB adapter and an
explicit (monitor-driven) predictor. pyuvm ships no uvm_reg_predictor body, so
MlaccRegPredictor implements the IEEE 1800.2 predictor behaviour here."""
from pyuvm import (uvm_reg, uvm_reg_field, uvm_reg_block, uvm_reg_adapter, uvm_reg_item,
                   uvm_subscriber, uvm_endianness_e, uvm_status_e, uvm_access_e,
                   uvm_predict_e, uvm_door_e)

from mlacc_tb.apb_agent import ApbItem

# (name, offset, [(field, lsb, size, access, volatile, reset)])
REG_SPEC = [
    ("ID",         0x000, [("id", 0, 32, "RO", False, 0x4D4C4143)]),
    ("VERSION",    0x004, [("version", 0, 32, "RO", False, 0x00010000)]),
    ("CTRL",       0x008, [("en", 0, 1, "RW", False, 0),
                           ("irq_en_done", 1, 1, "RW", False, 0),
                           ("irq_en_sat", 2, 1, "RW", False, 0),
                           ("irq_en_err", 3, 1, "RW", False, 0)]),
    ("STATUS",     0x00C, [("busy", 0, 1, "RO", True, 0),
                           ("fifo_level", 4, 4, "RO", True, 0)]),
    ("MLSTAT",     0x010, [("sat", 0, 1, "W1C", True, 0)]),
    ("IRQ_STATUS", 0x014, [("done", 0, 1, "W1C", True, 0),
                           ("sat", 1, 1, "W1C", True, 0),
                           ("err", 2, 1, "W1C", True, 0)]),
    ("CMD_COUNT",  0x018, [("count", 0, 32, "RO", True, 0)]),
    ("RSP_COUNT",  0x01C, [("count", 0, 32, "RO", True, 0)]),
    ("SCRATCH",    0x020, [("data", 0, 32, "RW", False, 0)]),
]
UNMAPPED_PROBES = [0x024, 0x028, 0x0FC, 0x100, 0x7FC, 0xFFC]


class MlaccReg(uvm_reg):
    """Generic 32-bit register built from a REG_SPEC row."""

    def __init__(self, name, fields):
        super().__init__(name, 32)
        self._spec = fields
        self.f = {}

    def build(self):
        for fname, lsb, size, access, volatile, reset in self._spec:
            fld = uvm_reg_field(fname)
            fld.configure(self, size, lsb, access, volatile, reset, True, False, True)
            self.f[fname] = fld

    def is_volatile(self):
        return any(v for _, _, _, _, v, _ in self._spec)

    def rights(self):
        acc = {a for _, _, _, a, _, _ in self._spec}
        return "RO" if acc == {"RO"} else "RW"


class MlaccRegBlock(uvm_reg_block):
    def __init__(self, name="mlacc_regs"):
        super().__init__(name)
        self.map = self.create_map("apb_map", 0x0, 4, uvm_endianness_e.UVM_LITTLE_ENDIAN)
        self.set_default_map(self.map)
        self.regs = {}
        for rname, off, fields in REG_SPEC:
            r = MlaccReg(rname, fields)
            r.configure(self)
            r.build()
            self.map.add_reg(r, off, r.rights())
            self.regs[rname] = r
            setattr(self, rname, r)
        self.lock_model()
        self.reset()

    def addr_of(self, rname):
        return dict((n, o) for n, o, _ in REG_SPEC)[rname]


class ApbRegAdapter(uvm_reg_adapter):
    def __init__(self, name="apb_reg_adapter"):
        super().__init__(name)
        self.supports_byte_enable = False
        self.provides_responses = False

    def reg2bus(self, rw):
        return ApbItem("reg_apb", addr=rw.addr, write=(rw.kind == uvm_access_e.UVM_WRITE),
                       data=rw.data if rw.kind == uvm_access_e.UVM_WRITE else 0)

    def bus2reg(self, bus_item, rw):
        rw.kind = uvm_access_e.UVM_WRITE if bus_item.write else uvm_access_e.UVM_READ
        rw.addr = bus_item.addr
        rw.data = bus_item.data
        rw.status = uvm_status_e.UVM_NOT_OK if bus_item.slverr else uvm_status_e.UVM_IS_OK


class MlaccRegPredictor(uvm_subscriber):
    """Explicit predictor: updates the RAL mirror from every observed APB transfer,
    whoever initiated it (RAL sequences or raw APB sequences)."""

    def build_phase(self):
        self.reg_model = None   # set by the env
        self.adapter = None
        self.n_predicted = 0

    def write(self, tr):
        rw_op = type("busop", (), {})()
        self.adapter.bus2reg(tr, rw_op)
        if rw_op.status != uvm_status_e.UVM_IS_OK:
            return
        rg = self.reg_model.map.get_reg_by_offset(rw_op.addr, rw_op.kind == uvm_access_e.UVM_READ)
        if rg is None:
            return
        item = uvm_reg_item("pred")
        item.set_value(rw_op.data)
        item.set_door(uvm_door_e.UVM_PREDICT)
        item.set_map(self.reg_model.map)
        item.set_status(uvm_status_e.UVM_IS_OK)
        kind = (uvm_predict_e.UVM_PREDICT_WRITE if rw_op.kind == uvm_access_e.UVM_WRITE
                else uvm_predict_e.UVM_PREDICT_READ)
        rg.do_predict(item, kind)
        self.n_predicted += 1
