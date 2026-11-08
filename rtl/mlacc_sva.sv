// mlacc_sva.sv — protocol and design assertions for MLACC, bound into mlacc_top.
//
// Icarus (the CI simulator) does not support concurrent SVA, so CI runs the
// equivalent pyuvm protocol checkers (tb/mlacc_tb/checkers.py). This file is
// linted with Verilator in CI and is ready for any simulator with SVA support.
`ifndef MLACC_SVA_SV
`define MLACC_SVA_SV
module mlacc_sva
  import mlacc_pkg::*;
(
  input logic              clk,
  input logic              rst_n,
  input logic              psel,
  input logic              penable,
  input logic              pwrite,
  input logic [11:0]       paddr,
  input logic [31:0]       pwdata,
  input logic              cmd_valid,
  input logic              cmd_ready,
  input logic [TAG_W-1:0]  cmd_tag,
  input logic [2:0]        cmd_op,
  input logic [XLEN-1:0]   cmd_rs1,
  input logic              rsp_valid,
  input logic              rsp_ready,
  input logic [TAG_W-1:0]  rsp_tag,
  input logic [XLEN-1:0]   rsp_result,
  input logic              rsp_sat,
  input logic [2:0]        fifo_count,
  input logic              s1_valid
);
  default clocking cb @(posedge clk); endclocking

  // ---- APB3 master rules (assumptions on the environment) ----
  a_apb_setup_then_access: assume property (disable iff (!rst_n) psel && !penable |=> psel && penable);
  a_apb_stable_ctrl:       assume property (disable iff (!rst_n) psel && !penable |=> $stable({pwrite, paddr, pwdata}));

  // ---- command stream (environment) ----
  a_cmd_hold: assume property (disable iff (!rst_n) cmd_valid && !cmd_ready |=> cmd_valid);
  a_cmd_stable: assume property (disable iff (!rst_n) cmd_valid && !cmd_ready |=> $stable({cmd_tag, cmd_op, cmd_rs1}));

  // ---- result stream (design obligations) ----
  p_rsp_hold:   assert property (disable iff (!rst_n) rsp_valid && !rsp_ready |=> rsp_valid);
  p_rsp_stable: assert property (disable iff (!rst_n) rsp_valid && !rsp_ready |=> $stable({rsp_tag, rsp_result, rsp_sat}));

  // ---- internal ----
  p_no_overflow: assert property (disable iff (!rst_n) fifo_count <= 3'(FIFO_DEPTH));
  p_credit:      assert property (disable iff (!rst_n) cmd_valid && cmd_ready |-> (fifo_count + 3'(s1_valid)) < 3'(FIFO_DEPTH));
  // 2-cycle latency, split into its two single-cycle steps:
  p_lat_s1:      assert property (disable iff (!rst_n) cmd_valid && cmd_ready |=> s1_valid);
  p_lat_fifo:    assert property (disable iff (!rst_n) s1_valid |=> rsp_valid);

  // ---- coverage ----
  c_fifo_full:     cover property (fifo_count == 3'(FIFO_DEPTH));
  c_backpressure:  cover property ($past(rsp_valid && !rsp_ready) && rsp_valid && rsp_ready);
  c_cmd_stall:     cover property (cmd_valid && !cmd_ready);
endmodule : mlacc_sva

bind mlacc_top mlacc_sva u_sva (
  .clk, .rst_n, .psel, .penable, .pwrite, .paddr, .pwdata,
  .cmd_valid, .cmd_ready, .cmd_tag, .cmd_op, .cmd_rs1,
  .rsp_valid, .rsp_ready, .rsp_tag, .rsp_result, .rsp_sat,
  .fifo_count, .s1_valid
);
`endif
