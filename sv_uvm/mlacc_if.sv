// mlacc_if.sv — interfaces for the SystemVerilog UVM bench.
interface apb_if (input logic clk, input logic rst_n);
  logic        psel, penable, pwrite, pready, pslverr;
  logic [11:0] paddr;
  logic [31:0] pwdata, prdata;
endinterface

interface cmd_if (input logic clk, input logic rst_n);
  logic        valid, ready;
  logic [7:0]  tag;
  logic [2:0]  op;
  logic [63:0] rs1, rs2, rs3;
endinterface

interface rsp_if (input logic clk, input logic rst_n);
  logic        valid, ready, sat;
  logic [7:0]  tag;
  logic [63:0] result;
endinterface
