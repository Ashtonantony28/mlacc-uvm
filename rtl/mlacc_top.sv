// mlacc_top.sv — MLACC v1: Vortex-V Xmlacc Tier-1 datapath as an APB + stream IP.
//
//   cmd (valid/ready) -> s1 register -> vortex_xmlacc (comb) -> result FIFO -> rsp (valid/ready)
//
// Latency is 2 cycles from cmd handshake to rsp_valid when the FIFO is not
// backed up. Flow control is credit based: a command is accepted only if the
// FIFO has room for it plus the one already in s1, so s1 never stalls and
// there is no combinational path from rsp_ready to cmd_ready.
// Illegal op codes return result 0 / sat 0 and set IRQ_STATUS.ERR.
`ifndef MLACC_TOP_SV
`define MLACC_TOP_SV
module mlacc_top
  import mlacc_pkg::*;
(
  input  logic              clk,
  input  logic              rst_n,
  // APB3 CSR port
  input  logic              psel,
  input  logic              penable,
  input  logic              pwrite,
  input  logic [11:0]       paddr,
  input  logic [31:0]       pwdata,
  output logic [31:0]       prdata,
  output logic              pready,
  output logic              pslverr,
  // command stream
  input  logic              cmd_valid,
  output logic              cmd_ready,
  input  logic [TAG_W-1:0]  cmd_tag,
  input  logic [2:0]        cmd_op,
  input  logic [XLEN-1:0]   cmd_rs1,
  input  logic [XLEN-1:0]   cmd_rs2,
  input  logic [XLEN-1:0]   cmd_rs3,
  // result stream
  output logic              rsp_valid,
  input  logic              rsp_ready,
  output logic [TAG_W-1:0]  rsp_tag,
  output logic [XLEN-1:0]   rsp_result,
  output logic              rsp_sat,
  // interrupt
  output logic              irq
);
  localparam int unsigned RW = TAG_W + XLEN + 1;   // {tag, result, sat}

  logic ctrl_en;
  logic cmd_fire, rsp_fire;

  // ---------------- stage 1 ----------------
  logic             s1_valid;
  logic [TAG_W-1:0] s1_tag;
  logic [2:0]       s1_op;
  logic [XLEN-1:0]  s1_rs1, s1_rs2, s1_rs3;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      s1_valid <= 1'b0;
    end else begin
      s1_valid <= cmd_fire;
    end
    if (cmd_fire) begin
      s1_tag <= cmd_tag;
      s1_op  <= cmd_op;
      s1_rs1 <= cmd_rs1;
      s1_rs2 <= cmd_rs2;
      s1_rs3 <= cmd_rs3;
    end
  end

  // ---------------- datapath (unchanged Vortex-V unit) ----------------
  logic [XLEN-1:0] dp_result;
  logic            dp_sat;
  vortex_xmlacc #(.XLEN(XLEN)) u_dp (
    .op     (vortex_pkg::xmlacc_op_e'(s1_op)),
    .rs1    (s1_rs1),
    .rs2    (s1_rs2),
    .rs3    (s1_rs3),
    .result (dp_result),
    .sat    (dp_sat)
  );

  logic            s1_legal;
  logic [XLEN-1:0] s1_result;
  logic            s1_sat;
  assign s1_legal  = op_is_legal(s1_op);
`ifdef MUTANT_ILLEGAL_OP
  assign s1_result = dp_result;                                   // MUTANT: illegal op not zeroed
`else
  assign s1_result = s1_legal ? dp_result : '0;
`endif
`ifdef MUTANT_SAT_STUCK
  assign s1_sat    = 1'b0;                                        // MUTANT: SAT never reported
`else
  assign s1_sat    = s1_legal & dp_sat;
`endif

  // ---------------- result FIFO ----------------
  logic [RW-1:0]                 fifo_rdata;
  logic                          fifo_empty, fifo_full;
  logic [$clog2(FIFO_DEPTH):0]   fifo_count;

  mlacc_fifo #(.WIDTH(RW), .DEPTH(FIFO_DEPTH)) u_fifo (
    .clk   (clk),
    .rst_n (rst_n),
`ifdef MUTANT_TAG_SWAP
    .push  (s1_valid),
    .wdata ({s1_tag ^ {7'b0, s1_op[2]}, s1_result, s1_sat}),     // MUTANT: tag corrupted for macc/rqs
`else
    .push  (s1_valid),
    .wdata ({s1_tag, s1_result, s1_sat}),
`endif
    .pop   (rsp_fire),
    .rdata (fifo_rdata),
    .empty (fifo_empty),
    .full  (fifo_full),
    .count (fifo_count)
  );

  assign rsp_valid = ~fifo_empty;
  assign {rsp_tag, rsp_result, rsp_sat} = fifo_rdata;
`ifdef MUTANT_RSP_NO_HOLD
  assign rsp_fire  = rsp_valid;                                   // MUTANT: pops without rsp_ready
`else
  assign rsp_fire  = rsp_valid & rsp_ready;
`endif

  // ---------------- flow control ----------------
  // Room for this command and the one in s1.
`ifdef MUTANT_CREDIT_OFF_BY_ONE
  assign cmd_ready = ctrl_en & (({1'b0, fifo_count} + {3'b0, s1_valid}) <= 4'(FIFO_DEPTH));  // MUTANT: overflow
`else
  assign cmd_ready = ctrl_en & (({1'b0, fifo_count} + {3'b0, s1_valid}) <  4'(FIFO_DEPTH));
`endif
  assign cmd_fire  = cmd_valid & cmd_ready;

  // ---------------- CSRs ----------------
  mlacc_csr u_csr (
    .clk        (clk),
    .rst_n      (rst_n),
    .psel       (psel),
    .penable    (penable),
    .pwrite     (pwrite),
    .paddr      (paddr),
    .pwdata     (pwdata),
    .prdata     (prdata),
    .pready     (pready),
    .pslverr    (pslverr),
    .ctrl_en    (ctrl_en),
    .irq        (irq),
    .ev_cmd     (cmd_fire),
    .ev_rsp     (rsp_fire),
    .ev_sat     (s1_valid & s1_sat),
    .ev_err     (s1_valid & ~s1_legal),
    .busy       (s1_valid | ~fifo_empty),
    .fifo_level ({1'b0, fifo_count})
  );

  logic unused;
  assign unused = fifo_full;
endmodule : mlacc_top
`endif
