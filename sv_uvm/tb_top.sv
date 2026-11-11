// tb_top.sv — SystemVerilog UVM top: clock, reset, DUT, interfaces, run_test().
module tb_top;
  import uvm_pkg::*;
  import mlacc_uvm_pkg::*;

  logic clk = 1'b0, rst_n = 1'b0;
  always #5 clk = ~clk;
  initial begin
    repeat (5) @(posedge clk);
    rst_n <= 1'b1;
  end

  apb_if apb (clk, rst_n);
  cmd_if cmd (clk, rst_n);
  rsp_if rsp (clk, rst_n);
  logic  irq;

  mlacc_top dut (
    .clk, .rst_n,
    .psel(apb.psel), .penable(apb.penable), .pwrite(apb.pwrite), .paddr(apb.paddr),
    .pwdata(apb.pwdata), .prdata(apb.prdata), .pready(apb.pready), .pslverr(apb.pslverr),
    .cmd_valid(cmd.valid), .cmd_ready(cmd.ready), .cmd_tag(cmd.tag), .cmd_op(cmd.op),
    .cmd_rs1(cmd.rs1), .cmd_rs2(cmd.rs2), .cmd_rs3(cmd.rs3),
    .rsp_valid(rsp.valid), .rsp_ready(rsp.ready), .rsp_tag(rsp.tag),
    .rsp_result(rsp.result), .rsp_sat(rsp.sat),
    .irq
  );

  initial begin
    uvm_config_db#(virtual apb_if)::set(null, "*", "apb_vif", apb);
    uvm_config_db#(virtual cmd_if)::set(null, "*", "cmd_vif", cmd);
    uvm_config_db#(virtual rsp_if)::set(null, "*", "rsp_vif", rsp);
    run_test();
  end
endmodule
