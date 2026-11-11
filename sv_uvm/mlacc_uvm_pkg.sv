// mlacc_uvm_pkg.sv — SystemVerilog UVM (IEEE 1800.2) bench for MLACC.
// Same architecture as the pyuvm bench in tb/: APB / command / result agents,
// a RAL model with the standard uvm_reg_predictor, an in-order scoreboard with a
// SystemVerilog port of the Vortex-V golden model, covergroups, and tests that
// include the UVM library's built-in register sequences.
package mlacc_uvm_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // =====================================================================
  // Reference model (port of Vortex-V model/xmlacc_model.py, unbounded rqs add)
  // =====================================================================
  function automatic void ref_exec(input logic [2:0] op, input logic [63:0] a, b, c,
                                   output logic [63:0] r, output bit sat);
    longint acc_ss = 0, acc_su = 0, acc_uu = 0;
    sat = 0;
    for (int i = 0; i < 8; i++) begin
      longint sa = longint'($signed(a[8*i +: 8]));
      longint sb = longint'($signed(b[8*i +: 8]));
      longint ua = longint'({56'b0, a[8*i +: 8]});
      longint ub = longint'({56'b0, b[8*i +: 8]});
      acc_ss += sa * sb;
      acc_su += sa * ub;
      acc_uu += ua * ub;
    end
    case (op)
      3'd0: r = acc_ss;
      3'd1: r = acc_uu;
      3'd2: r = acc_su;
      3'd4: r = c + acc_ss;
      3'd5: begin
        logic signed [65:0] x, t;
        int sh = int'(b[5:0]);
        x = 66'(signed'(a));
        if (sh > 0) x = x + (66'sd1 <<< (sh - 1));       // unbounded: no 64-bit wrap
        t = x >>> sh;
        if (t > 66'sd127) begin r = 64'd127; sat = 1; end
        else if (t < -66'sd128) begin r = -64'sd128; sat = 1; end
        else r = 64'(t);
      end
      default: r = '0;                                   // illegal op
    endcase
  endfunction

  // VTX-RQS-001 (docs/KNOWN-ISSUES.md): the Vortex-V RTL wraps rs1 + 2^(sh-1) at 64 bits.
  function automatic bit is_vtx_rqs_001(logic [2:0] op, logic [63:0] a, logic [63:0] b);
    logic signed [65:0] s;
    int sh = int'(b[5:0]);
    if (op != 3'd5 || sh == 0) return 0;
    s = 66'(signed'(a)) + (66'sd1 <<< (sh - 1));
    return s > 66'sh7FFF_FFFF_FFFF_FFFF;
  endfunction

  // =====================================================================
  // Configuration
  // =====================================================================
  class mlacc_cfg extends uvm_object;
    `uvm_object_utils(mlacc_cfg)
    int unsigned cmd_idle_pct  = 20;   // % chance of an idle cycle before a command
    int unsigned rsp_stall_pct = 15;   // % chance rsp_ready is low in a cycle
    bit          waive_known   = 1;
    function new(string name = "mlacc_cfg"); super.new(name); endfunction
  endclass

  // =====================================================================
  // APB agent
  // =====================================================================
  class apb_item extends uvm_sequence_item;
    rand bit        write;
    rand bit [11:0] addr;
    rand bit [31:0] data;
    bit             slverr;
    `uvm_object_utils_begin(apb_item)
      `uvm_field_int(write, UVM_ALL_ON)
      `uvm_field_int(addr, UVM_ALL_ON)
      `uvm_field_int(data, UVM_ALL_ON)
      `uvm_field_int(slverr, UVM_ALL_ON)
    `uvm_object_utils_end
    function new(string name = "apb_item"); super.new(name); endfunction
  endclass

  typedef uvm_sequencer #(apb_item) apb_sequencer;

  class apb_driver extends uvm_driver #(apb_item);
    `uvm_component_utils(apb_driver)
    virtual apb_if vif;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      if (!uvm_config_db#(virtual apb_if)::get(this, "", "apb_vif", vif))
        `uvm_fatal("NOVIF", "apb_vif not set")
    endfunction
    task run_phase(uvm_phase phase);
      vif.psel <= 0; vif.penable <= 0; vif.pwrite <= 0; vif.paddr <= 0; vif.pwdata <= 0;
      @(posedge vif.rst_n);
      forever begin
        seq_item_port.get_next_item(req);
        @(posedge vif.clk);
        vif.psel <= 1; vif.penable <= 0; vif.pwrite <= req.write;
        vif.paddr <= req.addr; vif.pwdata <= req.write ? req.data : 32'h0;
        @(posedge vif.clk);
        vif.penable <= 1;
        do @(posedge vif.clk); while (!vif.pready);
        if (!req.write) req.data = vif.prdata;
        req.slverr = vif.pslverr;
        vif.psel <= 0; vif.penable <= 0;
        seq_item_port.item_done();
      end
    endtask
  endclass

  class apb_monitor extends uvm_monitor;
    `uvm_component_utils(apb_monitor)
    virtual apb_if vif;
    uvm_analysis_port #(apb_item) ap;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      ap = new("ap", this);
      void'(uvm_config_db#(virtual apb_if)::get(this, "", "apb_vif", vif));
    endfunction
    task run_phase(uvm_phase phase);
      forever begin
        @(posedge vif.clk);
        if (vif.rst_n && vif.psel && vif.penable && vif.pready) begin
          apb_item t = apb_item::type_id::create("t");
          t.write = vif.pwrite; t.addr = vif.paddr; t.slverr = vif.pslverr;
          t.data  = vif.pwrite ? vif.pwdata : vif.prdata;
          ap.write(t);
        end
      end
    endtask
  endclass

  class apb_agent extends uvm_agent;
    `uvm_component_utils(apb_agent)
    apb_sequencer sqr; apb_driver drv; apb_monitor mon;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      sqr = apb_sequencer::type_id::create("sqr", this);
      drv = apb_driver::type_id::create("drv", this);
      mon = apb_monitor::type_id::create("mon", this);
    endfunction
    function void connect_phase(uvm_phase phase);
      drv.seq_item_port.connect(sqr.seq_item_export);
    endfunction
  endclass

  // =====================================================================
  // Command agent
  // =====================================================================
  class cmd_item extends uvm_sequence_item;
    rand bit [7:0]  tag;
    rand bit [2:0]  op;
    rand bit [63:0] rs1, rs2, rs3;
    rand enum {C_ZERO, C_ONES, C_MAXP, C_MINN, C_RAND} c1, c2;
    rand bit [5:0]  sh;
    rand bit        near_max;

    constraint c_op   { op dist {3'd0 := 25, 3'd1 := 15, 3'd2 := 15, 3'd4 := 20, 3'd5 := 20,
                                 [3'd6:3'd7] := 2, 3'd3 := 1}; }
    constraint c_cls  { c1 dist {C_ZERO := 5, C_ONES := 5, C_MAXP := 10, C_MINN := 10, C_RAND := 70};
                        c2 dist {C_ZERO := 5, C_ONES := 5, C_MAXP := 10, C_MINN := 10, C_RAND := 70}; }
    constraint c_sh   { sh dist {0 := 5, 1 := 5, [2:15] := 40, [16:31] := 30, [32:62] := 12, 63 := 5}; }
    constraint c_near { near_max dist {0 := 9, 1 := 1}; }
    constraint c_ops  {
                        (op != 3'd5) && c1 == C_ZERO -> rs1 == 0;
                        (op != 3'd5) && c1 == C_ONES -> rs1 == '1;
                        (op != 3'd5) && c1 == C_MAXP -> rs1 == {8{8'h7F}};
                        (op != 3'd5) && c1 == C_MINN -> rs1 == {8{8'h80}};
                        (op != 3'd5) && c2 == C_ZERO -> rs2 == 0;
                        (op != 3'd5) && c2 == C_ONES -> rs2 == '1;
                        (op != 3'd5) && c2 == C_MAXP -> rs2 == {8{8'h7F}};
                        (op != 3'd5) && c2 == C_MINN -> rs2 == {8{8'h80}};
                        (op == 3'd5) -> rs2[5:0] == sh;
                        (op == 3'd5) && near_max -> rs1[63:40] == 24'h7F_FFFF; }

    `uvm_object_utils_begin(cmd_item)
      `uvm_field_int(tag, UVM_ALL_ON)
      `uvm_field_int(op, UVM_ALL_ON)
      `uvm_field_int(rs1, UVM_ALL_ON)
      `uvm_field_int(rs2, UVM_ALL_ON)
      `uvm_field_int(rs3, UVM_ALL_ON)
    `uvm_object_utils_end
    function new(string name = "cmd_item"); super.new(name); endfunction
    function string convert2string();
      return $sformatf("tag=%0d op=%0d rs1=%h rs2=%h rs3=%h", tag, op, rs1, rs2, rs3);
    endfunction
  endclass

  class rsp_item extends uvm_sequence_item;
    bit [7:0] tag; bit [63:0] result; bit sat;
    `uvm_object_utils(rsp_item)
    function new(string name = "rsp_item"); super.new(name); endfunction
    function string convert2string();
      return $sformatf("tag=%0d result=%h sat=%0d", tag, result, sat);
    endfunction
  endclass

  typedef uvm_sequencer #(cmd_item) cmd_sequencer;

  class cmd_driver extends uvm_driver #(cmd_item);
    `uvm_component_utils(cmd_driver)
    virtual cmd_if vif;
    mlacc_cfg cfg;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      void'(uvm_config_db#(virtual cmd_if)::get(this, "", "cmd_vif", vif));
      void'(uvm_config_db#(mlacc_cfg)::get(this, "", "cfg", cfg));
    endfunction
    task run_phase(uvm_phase phase);
      vif.valid <= 0; vif.tag <= 0; vif.op <= 0; vif.rs1 <= 0; vif.rs2 <= 0; vif.rs3 <= 0;
      @(posedge vif.rst_n);
      @(posedge vif.clk);
      forever begin
        seq_item_port.get_next_item(req);
        while ($urandom_range(99) < cfg.cmd_idle_pct) begin
          vif.valid <= 0; @(posedge vif.clk);
        end
        vif.valid <= 1; vif.tag <= req.tag; vif.op <= req.op;
        vif.rs1 <= req.rs1; vif.rs2 <= req.rs2; vif.rs3 <= req.rs3;
        do @(posedge vif.clk); while (!vif.ready);
        vif.valid <= 0;
        seq_item_port.item_done();
      end
    endtask
  endclass

  class cmd_monitor extends uvm_monitor;
    `uvm_component_utils(cmd_monitor)
    virtual cmd_if vif;
    uvm_analysis_port #(cmd_item) ap;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      ap = new("ap", this);
      void'(uvm_config_db#(virtual cmd_if)::get(this, "", "cmd_vif", vif));
    endfunction
    task run_phase(uvm_phase phase);
      forever begin
        @(posedge vif.clk);
        if (vif.rst_n && vif.valid && vif.ready) begin
          cmd_item t = cmd_item::type_id::create("t");
          t.tag = vif.tag; t.op = vif.op; t.rs1 = vif.rs1; t.rs2 = vif.rs2; t.rs3 = vif.rs3;
          ap.write(t);
        end
      end
    endtask
  endclass

  class rsp_responder extends uvm_component;   // reactive slave: random rsp_ready
    `uvm_component_utils(rsp_responder)
    virtual rsp_if vif;
    mlacc_cfg cfg;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      void'(uvm_config_db#(virtual rsp_if)::get(this, "", "rsp_vif", vif));
      void'(uvm_config_db#(mlacc_cfg)::get(this, "", "cfg", cfg));
    endfunction
    task run_phase(uvm_phase phase);
      vif.ready <= 0;
      @(posedge vif.rst_n);
      forever begin
        @(posedge vif.clk);
        vif.ready <= ($urandom_range(99) >= cfg.rsp_stall_pct);
      end
    endtask
  endclass

  class rsp_monitor extends uvm_monitor;
    `uvm_component_utils(rsp_monitor)
    virtual rsp_if vif;
    uvm_analysis_port #(rsp_item) ap;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      ap = new("ap", this);
      void'(uvm_config_db#(virtual rsp_if)::get(this, "", "rsp_vif", vif));
    endfunction
    task run_phase(uvm_phase phase);
      forever begin
        @(posedge vif.clk);
        if (vif.rst_n && vif.valid && vif.ready) begin
          rsp_item t = rsp_item::type_id::create("t");
          t.tag = vif.tag; t.result = vif.result; t.sat = vif.sat;
          ap.write(t);
        end
      end
    endtask
  endclass

  // =====================================================================
  // RAL model
  // =====================================================================
  class reg_ro32 extends uvm_reg;
    `uvm_object_utils(reg_ro32)
    uvm_reg_field f;
    function new(string name = "reg_ro32"); super.new(name, 32, UVM_NO_COVERAGE); endfunction
    function void build_ro(uvm_reg_data_t rst, bit vol);
      f = uvm_reg_field::type_id::create("f");
      f.configure(this, 32, 0, "RO", vol, rst, 1, 0, 1);
    endfunction
  endclass

  class reg_ctrl extends uvm_reg;
    `uvm_object_utils(reg_ctrl)
    rand uvm_reg_field en, irq_en_done, irq_en_sat, irq_en_err;
    function new(string name = "reg_ctrl"); super.new(name, 32, UVM_NO_COVERAGE); endfunction
    virtual function void build();
      en          = uvm_reg_field::type_id::create("en");
      irq_en_done = uvm_reg_field::type_id::create("irq_en_done");
      irq_en_sat  = uvm_reg_field::type_id::create("irq_en_sat");
      irq_en_err  = uvm_reg_field::type_id::create("irq_en_err");
      en.configure         (this, 1, 0, "RW", 0, 0, 1, 1, 0);
      irq_en_done.configure(this, 1, 1, "RW", 0, 0, 1, 1, 0);
      irq_en_sat.configure (this, 1, 2, "RW", 0, 0, 1, 1, 0);
      irq_en_err.configure (this, 1, 3, "RW", 0, 0, 1, 1, 0);
    endfunction
  endclass

  class reg_status extends uvm_reg;
    `uvm_object_utils(reg_status)
    uvm_reg_field busy, fifo_level;
    function new(string name = "reg_status"); super.new(name, 32, UVM_NO_COVERAGE); endfunction
    virtual function void build();
      busy       = uvm_reg_field::type_id::create("busy");
      fifo_level = uvm_reg_field::type_id::create("fifo_level");
      busy.configure      (this, 1, 0, "RO", 1, 0, 1, 0, 0);
      fifo_level.configure(this, 4, 4, "RO", 1, 0, 1, 0, 0);
    endfunction
  endclass

  class reg_mlstat extends uvm_reg;
    `uvm_object_utils(reg_mlstat)
    uvm_reg_field sat;
    function new(string name = "reg_mlstat"); super.new(name, 32, UVM_NO_COVERAGE); endfunction
    virtual function void build();
      sat = uvm_reg_field::type_id::create("sat");
      sat.configure(this, 1, 0, "W1C", 1, 0, 1, 0, 0);
    endfunction
  endclass

  class reg_irq_status extends uvm_reg;
    `uvm_object_utils(reg_irq_status)
    uvm_reg_field done, sat, err;
    function new(string name = "reg_irq_status"); super.new(name, 32, UVM_NO_COVERAGE); endfunction
    virtual function void build();
      done = uvm_reg_field::type_id::create("done");
      sat  = uvm_reg_field::type_id::create("sat");
      err  = uvm_reg_field::type_id::create("err");
      done.configure(this, 1, 0, "W1C", 1, 0, 1, 0, 0);
      sat.configure (this, 1, 1, "W1C", 1, 0, 1, 0, 0);
      err.configure (this, 1, 2, "W1C", 1, 0, 1, 0, 0);
    endfunction
  endclass

  class reg_rw32 extends uvm_reg;
    `uvm_object_utils(reg_rw32)
    rand uvm_reg_field f;
    function new(string name = "reg_rw32"); super.new(name, 32, UVM_NO_COVERAGE); endfunction
    virtual function void build();
      f = uvm_reg_field::type_id::create("f");
      f.configure(this, 32, 0, "RW", 0, 0, 1, 1, 1);
    endfunction
  endclass

  class mlacc_reg_block extends uvm_reg_block;
    `uvm_object_utils(mlacc_reg_block)
    reg_ro32 ID, VERSION, CMD_COUNT, RSP_COUNT;
    reg_ctrl CTRL;
    reg_status STATUS;
    reg_mlstat MLSTAT;
    reg_irq_status IRQ_STATUS;
    reg_rw32 SCRATCH;
    uvm_reg_map apb_map;
    function new(string name = "mlacc_reg_block"); super.new(name, UVM_NO_COVERAGE); endfunction
    virtual function void build();
      apb_map = create_map("apb_map", 0, 4, UVM_LITTLE_ENDIAN);
      ID = reg_ro32::type_id::create("ID");                 ID.configure(this);        ID.build_ro(32'h4D4C4143, 0);
      VERSION = reg_ro32::type_id::create("VERSION");       VERSION.configure(this);   VERSION.build_ro(32'h0001_0000, 0);
      CTRL = reg_ctrl::type_id::create("CTRL");             CTRL.configure(this);      CTRL.build();
      STATUS = reg_status::type_id::create("STATUS");       STATUS.configure(this);    STATUS.build();
      MLSTAT = reg_mlstat::type_id::create("MLSTAT");       MLSTAT.configure(this);    MLSTAT.build();
      IRQ_STATUS = reg_irq_status::type_id::create("IRQ_STATUS"); IRQ_STATUS.configure(this); IRQ_STATUS.build();
      CMD_COUNT = reg_ro32::type_id::create("CMD_COUNT");   CMD_COUNT.configure(this); CMD_COUNT.build_ro(0, 1);
      RSP_COUNT = reg_ro32::type_id::create("RSP_COUNT");   RSP_COUNT.configure(this); RSP_COUNT.build_ro(0, 1);
      SCRATCH = reg_rw32::type_id::create("SCRATCH");       SCRATCH.configure(this);   SCRATCH.build();
      apb_map.add_reg(ID,         12'h000, "RO");
      apb_map.add_reg(VERSION,    12'h004, "RO");
      apb_map.add_reg(CTRL,       12'h008, "RW");
      apb_map.add_reg(STATUS,     12'h00C, "RO");
      apb_map.add_reg(MLSTAT,     12'h010, "RW");
      apb_map.add_reg(IRQ_STATUS, 12'h014, "RW");
      apb_map.add_reg(CMD_COUNT,  12'h018, "RO");
      apb_map.add_reg(RSP_COUNT,  12'h01C, "RO");
      apb_map.add_reg(SCRATCH,    12'h020, "RW");
      lock_model();
    endfunction
  endclass

  class apb_reg_adapter extends uvm_reg_adapter;
    `uvm_object_utils(apb_reg_adapter)
    function new(string name = "apb_reg_adapter");
      super.new(name);
      supports_byte_enable = 0;
      provides_responses = 0;
    endfunction
    virtual function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
      apb_item t = apb_item::type_id::create("t");
      t.write = (rw.kind == UVM_WRITE);
      t.addr  = rw.addr[11:0];
      t.data  = rw.data[31:0];
      return t;
    endfunction
    virtual function void bus2reg(uvm_sequence_item bus_item, ref uvm_reg_bus_op rw);
      apb_item t;
      if (!$cast(t, bus_item)) `uvm_fatal("CAST", "not an apb_item")
      rw.kind   = t.write ? UVM_WRITE : UVM_READ;
      rw.addr   = t.addr;
      rw.data   = t.data;
      rw.status = t.slverr ? UVM_NOT_OK : UVM_IS_OK;
    endfunction
  endclass

  // =====================================================================
  // Scoreboard + coverage
  // =====================================================================
  `uvm_analysis_imp_decl(_cmd)
  `uvm_analysis_imp_decl(_rsp)

  class mlacc_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(mlacc_scoreboard)
    uvm_analysis_imp_cmd #(cmd_item, mlacc_scoreboard) cmd_imp;
    uvm_analysis_imp_rsp #(rsp_item, mlacc_scoreboard) rsp_imp;
    cmd_item pending[$];
    int unsigned n_checked, n_errors, n_waived, n_cmds;
    mlacc_cfg cfg;

    covergroup cg_cmd with function sample(cmd_item c);
      cp_op:  coverpoint c.op { bins dot8 = {0}; bins dot8u = {1}; bins dot8su = {2};
                                bins macc = {4}; bins rqs = {5}; bins illegal = {3, 6, 7}; }
      cp_sh:  coverpoint c.rs2[5:0] iff (c.op == 5) { bins sh0 = {0}; bins sh1 = {1};
                                bins lo = {[2:15]}; bins mid = {[16:31]}; bins hi = {[32:62]};
                                bins sh63 = {63}; }
      cp_rs1: coverpoint c.rs1 { bins zero = {0}; bins ones = {64'hFFFF_FFFF_FFFF_FFFF};
                                 bins maxp = {64'h7F7F_7F7F_7F7F_7F7F};
                                 bins minn = {64'h8080_8080_8080_8080}; bins other = default; }
      x_op_rs1: cross cp_op, cp_rs1 { ignore_bins i = binsof(cp_op.illegal) || binsof(cp_op.rqs); }
    endgroup

    function new(string name, uvm_component parent);
      super.new(name, parent);
      cg_cmd = new();
    endfunction
    function void build_phase(uvm_phase phase);
      cmd_imp = new("cmd_imp", this);
      rsp_imp = new("rsp_imp", this);
      void'(uvm_config_db#(mlacc_cfg)::get(this, "", "cfg", cfg));
    endfunction
    function void write_cmd(cmd_item c);
      pending.push_back(c);
      n_cmds++;
      cg_cmd.sample(c);
    endfunction
    function void write_rsp(rsp_item r);
      cmd_item c;
      logic [63:0] exp; bit exp_sat;
      if (pending.size() == 0) begin
        n_errors++;
        `uvm_error("SB", $sformatf("result with nothing in flight: %s", r.convert2string()))
        return;
      end
      c = pending.pop_front();
      ref_exec(c.op, c.rs1, c.rs2, c.rs3, exp, exp_sat);
      n_checked++;
      if (r.tag !== c.tag || r.result !== exp || r.sat !== exp_sat) begin
        if (cfg.waive_known && r.tag == c.tag && is_vtx_rqs_001(c.op, c.rs1, c.rs2)) begin
          n_waived++;
          return;
        end
        n_errors++;
        `uvm_error("SB", $sformatf("MISMATCH %s\n   got  %s\n   want result=%h sat=%0d",
                                   c.convert2string(), r.convert2string(), exp, exp_sat))
      end
    endfunction
    function void check_phase(uvm_phase phase);
      if (pending.size() != 0)
        `uvm_error("SB", $sformatf("%0d command(s) never returned", pending.size()))
    endfunction
    function void report_phase(uvm_phase phase);
      `uvm_info("SB", $sformatf("%0d results checked, %0d errors, %0d waived as VTX-RQS-001, cg_cmd %.1f%%",
                                n_checked, n_errors, n_waived, cg_cmd.get_coverage()), UVM_NONE)
    endfunction
  endclass

  // =====================================================================
  // Environment
  // =====================================================================
  class mlacc_env extends uvm_env;
    `uvm_component_utils(mlacc_env)
    apb_agent apb;
    cmd_sequencer cmd_sqr; cmd_driver cmd_drv; cmd_monitor cmd_mon;
    rsp_responder rsp_drv; rsp_monitor rsp_mon;
    mlacc_reg_block regs;
    apb_reg_adapter adapter;
    uvm_reg_predictor #(apb_item) predictor;
    mlacc_scoreboard sb;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      apb     = apb_agent::type_id::create("apb", this);
      cmd_sqr = cmd_sequencer::type_id::create("cmd_sqr", this);
      cmd_drv = cmd_driver::type_id::create("cmd_drv", this);
      cmd_mon = cmd_monitor::type_id::create("cmd_mon", this);
      rsp_drv = rsp_responder::type_id::create("rsp_drv", this);
      rsp_mon = rsp_monitor::type_id::create("rsp_mon", this);
      sb      = mlacc_scoreboard::type_id::create("sb", this);
      regs    = mlacc_reg_block::type_id::create("regs");
      regs.build();
      adapter   = apb_reg_adapter::type_id::create("adapter");
      predictor = uvm_reg_predictor#(apb_item)::type_id::create("predictor", this);
    endfunction
    function void connect_phase(uvm_phase phase);
      cmd_drv.seq_item_port.connect(cmd_sqr.seq_item_export);
      cmd_mon.ap.connect(sb.cmd_imp);
      rsp_mon.ap.connect(sb.rsp_imp);
      regs.apb_map.set_sequencer(apb.sqr, adapter);
      regs.apb_map.set_auto_predict(0);
      predictor.map = regs.apb_map;
      predictor.adapter = adapter;
      apb.mon.ap.connect(predictor.bus_in);
    endfunction
  endclass

  // =====================================================================
  // Sequences
  // =====================================================================
  class rand_cmd_seq extends uvm_sequence #(cmd_item);
    `uvm_object_utils(rand_cmd_seq)
    int unsigned n = 100;
    static bit [7:0] next_tag;
    function new(string name = "rand_cmd_seq"); super.new(name); endfunction
    task body();
      repeat (n) begin
        req = cmd_item::type_id::create("req");
        start_item(req);
        if (!req.randomize())
          `uvm_fatal("RAND", "cmd_item randomize failed")
        req.tag = next_tag++;
        finish_item(req);
      end
    endtask
  endclass

  // =====================================================================
  // Tests
  // =====================================================================
  class mlacc_base_test extends uvm_test;
    `uvm_component_utils(mlacc_base_test)
    mlacc_env env;
    mlacc_cfg cfg;
    int unsigned n_cmds = 200;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    virtual function void configure(); endfunction
    function void build_phase(uvm_phase phase);
      cfg = mlacc_cfg::type_id::create("cfg");
      configure();
      uvm_config_db#(mlacc_cfg)::set(this, "*", "cfg", cfg);
      env = mlacc_env::type_id::create("env", this);
    endfunction
    task enable();
      uvm_status_e st;
      env.regs.CTRL.write(st, 32'h1);
      if (st != UVM_IS_OK) `uvm_error("REG", "CTRL write failed")
    endtask
    task drain();
      int unsigned guard = 0;
      while ((env.sb.pending.size() != 0) && guard++ < 10000) #10ns;
      #50ns;
    endtask
    virtual task body();
      rand_cmd_seq s = rand_cmd_seq::type_id::create("s");
      s.n = n_cmds;
      s.start(env.cmd_sqr);
    endtask
    task check_counters();
      uvm_status_e st; uvm_reg_data_t v;
      env.regs.CMD_COUNT.read(st, v);
      if (v != env.sb.n_cmds) `uvm_error("REG", $sformatf("CMD_COUNT=%0d, scoreboard saw %0d", v, env.sb.n_cmds))
      env.regs.RSP_COUNT.read(st, v);
      if (v != env.sb.n_checked) `uvm_error("REG", $sformatf("RSP_COUNT=%0d, scoreboard checked %0d", v, env.sb.n_checked))
    endtask
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #100ns;   // reset released at 50 ns in tb_top
      enable();
      body();
      drain();
      check_counters();
      phase.drop_objection(this);
    endtask
    function void report_phase(uvm_phase phase);
      uvm_report_server rs = uvm_report_server::get_server();
      int unsigned errs = rs.get_severity_count(UVM_ERROR) + rs.get_severity_count(UVM_FATAL);
      `uvm_info("RESULT", errs == 0 ? "*** TEST PASSED ***" : $sformatf("*** TEST FAILED (%0d errors) ***", errs), UVM_NONE)
    endfunction
  endclass

  class smoke_test extends mlacc_base_test;
    `uvm_component_utils(smoke_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    virtual function void configure(); n_cmds = 50; cfg.cmd_idle_pct = 0; cfg.rsp_stall_pct = 0; endfunction
  endclass

  class random_test extends mlacc_base_test;
    `uvm_component_utils(random_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    virtual function void configure(); n_cmds = 2000; endfunction
  endclass

  class stress_test extends mlacc_base_test;
    `uvm_component_utils(stress_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    virtual function void configure(); n_cmds = 3000; cfg.cmd_idle_pct = 0; cfg.rsp_stall_pct = 50; endfunction
  endclass

  // Built-in UVM register sequences: hardware reset values and bit-bash of the RW registers.
  class reg_builtin_test extends mlacc_base_test;
    `uvm_component_utils(reg_builtin_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    task run_phase(uvm_phase phase);
      uvm_reg_hw_reset_seq rst_seq;
      uvm_reg_bit_bash_seq bb_seq;
      phase.raise_objection(this);
      #100ns;
      // counters / status change on their own and W1C bits cannot be bit-bashed
      foreach (volatile_regs[i])
        uvm_resource_db#(bit)::set({"REG::", volatile_regs[i]}, "NO_REG_BIT_BASH_TEST", 1, this);
      rst_seq = uvm_reg_hw_reset_seq::type_id::create("rst_seq");
      rst_seq.model = env.regs;
      rst_seq.start(null);
      bb_seq = uvm_reg_bit_bash_seq::type_id::create("bb_seq");
      bb_seq.model = env.regs;
      bb_seq.start(null);
      phase.drop_objection(this);
    endtask
    string volatile_regs[] = '{"regs.STATUS", "regs.MLSTAT", "regs.IRQ_STATUS",
                               "regs.CMD_COUNT", "regs.RSP_COUNT", "regs.ID", "regs.VERSION"};
  endclass
endpackage
