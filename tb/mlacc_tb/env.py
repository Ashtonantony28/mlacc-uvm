"""MLACC UVM environment."""
from pyuvm import uvm_env, ConfigDB, uvm_active_passive_enum

from mlacc_tb.apb_agent import ApbAgent
from mlacc_tb.stream_agents import CmdAgent, RspAgent, SignalMonitor
from mlacc_tb.ral import MlaccRegBlock, ApbRegAdapter, MlaccRegPredictor
from mlacc_tb.scoreboard import MlaccScoreboard, MlaccCycleModel
from mlacc_tb.checkers import ProtocolChecker
from mlacc_tb.coverage import MlaccCoverage


class MlaccEnv(uvm_env):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        ConfigDB().set(self, "*", "is_active", uvm_active_passive_enum.UVM_ACTIVE)
        self.apb = ApbAgent("apb", self)
        self.cmd = CmdAgent("cmd", self)
        self.rsp = RspAgent("rsp", self)
        self.sig = SignalMonitor("sig", self)
        self.regs = MlaccRegBlock("mlacc_regs")
        self.adapter = ApbRegAdapter()
        self.predictor = MlaccRegPredictor("predictor", self)
        self.scoreboard = MlaccScoreboard("scoreboard", self)
        self.cycle_model = MlaccCycleModel("cycle_model", self)
        self.protocol = ProtocolChecker("protocol", self)
        self.coverage = MlaccCoverage("coverage", self)

    def connect_phase(self):
        # RAL: frontdoor through the APB sequencer, mirror kept by the explicit predictor
        self.regs.map.set_sequencer(self.apb.sequencer, self.adapter)
        self.regs.map.set_auto_predict(False)
        self.predictor.reg_model = self.regs
        self.predictor.adapter = self.adapter
        self.apb.monitor.ap.connect(self.predictor.analysis_export)
        # data scoreboard
        self.cmd.monitor.ap.connect(self.scoreboard.cmd_tap.analysis_export)
        self.rsp.monitor.ap.connect(self.scoreboard.rsp_tap.analysis_export)
        self.sig.ap.connect(self.scoreboard.sig_tap.analysis_export)
        # cycle model + protocol
        self.sig.ap.connect(self.cycle_model.sig_tap.analysis_export)
        self.sig.ap.connect(self.protocol.sig_tap.analysis_export)
        # coverage
        if self.cfg.coverage_enabled:
            self.cmd.monitor.ap.connect(self.coverage.cmd_tap.analysis_export)
            self.apb.monitor.ap.connect(self.coverage.apb_tap.analysis_export)
            self.sig.ap.connect(self.coverage.sig_tap.analysis_export)
