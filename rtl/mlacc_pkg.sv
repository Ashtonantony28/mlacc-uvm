// mlacc_pkg.sv — MLACC v1 register map and constants (see docs/DUT-SPEC.md).
`ifndef MLACC_PKG_SV
`define MLACC_PKG_SV
package mlacc_pkg;
  localparam int unsigned XLEN       = 64;
  localparam int unsigned TAG_W      = 8;
  localparam int unsigned FIFO_DEPTH = 4;

  localparam logic [31:0] MLACC_ID      = 32'h4D4C_4143;   // "MLAC"
  localparam logic [31:0] MLACC_VERSION = 32'h0001_0000;

  // CSR byte addresses (APB, 32-bit word aligned)
  localparam logic [11:0] A_ID         = 12'h000;
  localparam logic [11:0] A_VERSION    = 12'h004;
  localparam logic [11:0] A_CTRL       = 12'h008;
  localparam logic [11:0] A_STATUS     = 12'h00C;
  localparam logic [11:0] A_MLSTAT     = 12'h010;
  localparam logic [11:0] A_IRQ_STATUS = 12'h014;
  localparam logic [11:0] A_CMD_COUNT  = 12'h018;
  localparam logic [11:0] A_RSP_COUNT  = 12'h01C;
  localparam logic [11:0] A_SCRATCH    = 12'h020;

  // CTRL bits
  localparam int unsigned CTRL_EN          = 0;
  localparam int unsigned CTRL_IRQ_EN_DONE = 1;
  localparam int unsigned CTRL_IRQ_EN_SAT  = 2;
  localparam int unsigned CTRL_IRQ_EN_ERR  = 3;
  localparam logic [31:0] CTRL_MASK        = 32'h0000_000F;

  // IRQ_STATUS bits (W1C)
  localparam int unsigned IRQ_DONE = 0;
  localparam int unsigned IRQ_SAT  = 1;
  localparam int unsigned IRQ_ERR  = 2;

  // Legal op codes are the Vortex-V Xmlacc funct3 values; others are illegal.
  function automatic logic op_is_legal(input logic [2:0] op);
    return (op == 3'b000) || (op == 3'b001) || (op == 3'b010) ||
           (op == 3'b100) || (op == 3'b101);
  endfunction
endpackage : mlacc_pkg
`endif
