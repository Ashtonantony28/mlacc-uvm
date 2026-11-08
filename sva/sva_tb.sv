// sva_tb.sv — runs the bound SVA (rtl/mlacc_sva.sv) under Verilator with random,
// protocol-legal stimulus. Complements the pyuvm protocol checkers: here the real
// SVA properties execute. Not a UVM bench; no scoreboard (that is the pyuvm env's job).
module sva_tb;
  import mlacc_pkg::*;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic psel = 0, penable = 0, pwrite = 0;
  logic [11:0] paddr = 0;
  logic [31:0] pwdata = 0, prdata;
  logic pready, pslverr;
  logic cmd_valid = 0, cmd_ready;
  logic [7:0] cmd_tag = 0;
  logic [2:0] cmd_op = 0;
  logic [63:0] cmd_rs1 = 0, cmd_rs2 = 0, cmd_rs3 = 0;
  logic rsp_valid, rsp_ready = 0, rsp_sat, irq;
  logic [7:0] rsp_tag;
  logic [63:0] rsp_result;

  mlacc_top dut (.*);

  logic cmd_fired;
  int unsigned n_cmd = 0, n_rsp = 0, cycles = 0;
  int unsigned seed;

  task automatic apb_write(input logic [11:0] a, input logic [31:0] d);
    @(negedge clk); psel = 1; penable = 0; pwrite = 1; paddr = a; pwdata = d;
    @(negedge clk); penable = 1;
    @(negedge clk); psel = 0; penable = 0;
  endtask

  initial begin
    if (!$value$plusargs("seed=%d", seed)) seed = 1;
    void'($urandom(seed));
    repeat (5) @(posedge clk);
    @(negedge clk) rst_n = 1;
    apb_write(A_CTRL, 32'h1);
    fork
      // Stimulus changes on the falling edge (race-free w.r.t. the sampled posedge).
      forever begin
        @(posedge clk);
        cmd_fired = cmd_valid && cmd_ready;
        if (cmd_fired) n_cmd++;
        if (rsp_valid && rsp_ready) n_rsp++;
        @(negedge clk);
        if (cmd_fired) cmd_valid = 0;
        if (!cmd_valid && ($urandom % 4 != 0)) begin   // payload only changes when not stalled
          cmd_valid = 1; cmd_tag = cmd_tag + 1; cmd_op = 3'($urandom);
          cmd_rs1 = {$urandom, $urandom}; cmd_rs2 = {$urandom, $urandom};
          cmd_rs3 = {$urandom, $urandom};
        end
        rsp_ready = ($urandom % 3 != 0);
      end
    join_none
    repeat (20000) @(posedge clk);
    $display("SVA_TB DONE seed=%0d cmds=%0d rsps=%0d", seed, n_cmd, n_rsp);
    $finish;
  end
endmodule
