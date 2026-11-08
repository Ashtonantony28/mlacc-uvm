"""Pin-level protocol checkers. These are the executable twin of rtl/mlacc_sva.sv
(Icarus cannot run concurrent SVA), checked every cycle from CycleSnapshot."""
from mlacc_tb.scoreboard import _Checker, _Tap
from mlacc_tb.stream_agents import ResetEvent


class ProtocolChecker(_Checker):
    def build_phase(self):
        self.sig_tap = _Tap("sig_tap", self, self.on_cycle)
        self.prev = None
        self.n_checks = 0

    def on_cycle(self, s):
        if isinstance(s, ResetEvent):
            self.prev = None
            return
        p = self.prev
        self.prev = s
        if p is None:                      # first cycle after reset
            if s.rsp_valid or s.irq:
                self.fail(f"[cyc {s.cycle}] rsp_valid/irq not low out of reset")
            return
        self.n_checks += 1
        # --- design obligations (assert) ---
        if p.rsp_valid and not p.rsp_ready:
            if not s.rsp_valid:
                self.fail(f"[cyc {s.cycle}] p_rsp_hold: rsp_valid dropped while stalled")
            elif s.rsp_payload != p.rsp_payload:
                self.fail(f"[cyc {s.cycle}] p_rsp_stable: result changed while stalled "
                          f"{p.rsp_payload} -> {s.rsp_payload}")
        if s.fifo_count > 4:
            self.fail(f"[cyc {s.cycle}] p_no_overflow: FIFO count {s.fifo_count}")
        if p.cmd_valid and p.cmd_ready and not s.s1_valid:
            self.fail(f"[cyc {s.cycle}] p_lat_s1: accepted command not in stage 1")
        if p.s1_valid and not s.rsp_valid:
            self.fail(f"[cyc {s.cycle}] p_lat_fifo: stage-1 result not visible on rsp")
        # --- environment rules (assume): a failure here is a testbench bug ---
        if p.cmd_valid and not p.cmd_ready:
            if not s.cmd_valid or s.cmd_payload != p.cmd_payload:
                self.fail(f"[cyc {s.cycle}] a_cmd_hold/stable violated by the TB driver")
        if p.psel and not p.penable:
            if not (s.psel and s.penable) or s.apb_payload != p.apb_payload:
                self.fail(f"[cyc {s.cycle}] APB setup->access rule violated by the TB driver")
        if s.penable and not s.psel:
            self.fail(f"[cyc {s.cycle}] APB PENABLE without PSEL")

    def report_phase(self):
        self.logger.info(f"protocol checker: {self.n_checks} cycles checked, {len(self.errors)} errors")
