// mlacc_csr.sv — APB3 slave register block for MLACC v1.
//
// Zero-wait-state APB3 (PREADY tied high). Unmapped addresses read 0, ignore
// writes and return PSLVERR in the access phase. Writes to RO registers are
// silently ignored (no error). For W1C bits a hardware set in the same cycle
// as a software clear wins (the event is never lost).
`ifndef MLACC_CSR_SV
`define MLACC_CSR_SV
module mlacc_csr
  import mlacc_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,
  // APB3
  input  logic        psel,
  input  logic        penable,
  input  logic        pwrite,
  input  logic [11:0] paddr,
  input  logic [31:0] pwdata,
  output logic [31:0] prdata,
  output logic        pready,
  output logic        pslverr,
  // core-side
  output logic        ctrl_en,
  output logic        irq,
  input  logic        ev_cmd,      // command accepted
  input  logic        ev_rsp,      // result delivered
  input  logic        ev_sat,      // rqs clamp fired
  input  logic        ev_err,      // illegal op executed
  input  logic        busy,
  input  logic [3:0]  fifo_level
);
  logic [31:0] ctrl_q, scratch_q, cmd_cnt_q, rsp_cnt_q;
  logic        mlstat_sat_q;
  logic [2:0]  irq_sts_q;

  logic apb_wr, apb_rd, addr_ok;
  assign apb_wr = psel & penable &  pwrite;
  assign apb_rd = psel & penable & ~pwrite;

  // Full 12-bit decode. MUTANT_ADDR_ALIAS decodes only paddr[7:0], so 0x100 aliases ID.
  logic [11:0] dec_addr;
`ifdef MUTANT_ADDR_ALIAS
  assign dec_addr = {4'h0, paddr[7:0]};
`else
  assign dec_addr = paddr;
`endif

  always_comb begin
    unique case (dec_addr)
      A_ID, A_VERSION, A_CTRL, A_STATUS, A_MLSTAT, A_IRQ_STATUS,
      A_CMD_COUNT, A_RSP_COUNT, A_SCRATCH: addr_ok = 1'b1;
      default:                             addr_ok = 1'b0;
    endcase
  end

  assign pready  = 1'b1;
  assign pslverr = psel & penable & ~addr_ok;

  // ---- read mux ----
  always_comb begin
    prdata = 32'h0;
    if (apb_rd) begin
      unique case (dec_addr)
        A_ID:         prdata = MLACC_ID;
        A_VERSION:    prdata = MLACC_VERSION;
        A_CTRL:       prdata = ctrl_q;
`ifdef MUTANT_STATUS_LEVEL
        A_STATUS:     prdata = {25'h0, fifo_level, 2'b00, busy};      // MUTANT: field at [6:3]
`else
        A_STATUS:     prdata = {24'h0, fifo_level, 3'b000, busy};
`endif
        A_MLSTAT:     prdata = {31'h0, mlstat_sat_q};
        A_IRQ_STATUS: prdata = {29'h0, irq_sts_q};
        A_CMD_COUNT:  prdata = cmd_cnt_q;
        A_RSP_COUNT:  prdata = rsp_cnt_q;
        A_SCRATCH:    prdata = scratch_q;
        default:      prdata = 32'h0;
      endcase
    end
  end

  // ---- registers ----
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      ctrl_q       <= '0;
      scratch_q    <= '0;
      cmd_cnt_q    <= '0;
      rsp_cnt_q    <= '0;
      mlstat_sat_q <= 1'b0;
      irq_sts_q    <= '0;
    end else begin
      if (apb_wr && paddr == A_CTRL)    ctrl_q    <= pwdata & CTRL_MASK;
`ifdef MUTANT_SCRATCH_BIT
      if (apb_wr && paddr == A_SCRATCH) scratch_q <= pwdata & 32'hFFFF_7FFF; // MUTANT: bit 15 stuck at 0
`else
      if (apb_wr && paddr == A_SCRATCH) scratch_q <= pwdata;
`endif

      // MLSTAT.SAT: sticky, W1C, set wins
`ifdef MUTANT_W1C_AS_RW
      if (apb_wr && paddr == A_MLSTAT) mlstat_sat_q <= pwdata[0];          // MUTANT: plain RW, not W1C
`else
      if (apb_wr && paddr == A_MLSTAT && pwdata[0]) mlstat_sat_q <= 1'b0;
`endif
      if (ev_sat) mlstat_sat_q <= 1'b1;

      // IRQ_STATUS: W1C, set wins
      if (apb_wr && paddr == A_IRQ_STATUS) irq_sts_q <= irq_sts_q & ~pwdata[2:0];
`ifndef MUTANT_DONE_LOST
      if (ev_rsp) irq_sts_q[IRQ_DONE] <= 1'b1;
`else
      if (ev_rsp && !(apb_wr && paddr == A_IRQ_STATUS)) irq_sts_q[IRQ_DONE] <= 1'b1; // MUTANT: clear wins
`endif
      if (ev_sat) irq_sts_q[IRQ_SAT]  <= 1'b1;
      if (ev_err) irq_sts_q[IRQ_ERR]  <= 1'b1;

      if (ev_cmd) cmd_cnt_q <= cmd_cnt_q + 32'd1;
`ifdef MUTANT_RSP_COUNT
      if (ev_rsp && rsp_cnt_q != 32'd7) rsp_cnt_q <= rsp_cnt_q + 32'd1;    // MUTANT: saturates at 7
`else
      if (ev_rsp) rsp_cnt_q <= rsp_cnt_q + 32'd1;
`endif
    end
  end

  assign ctrl_en = ctrl_q[CTRL_EN];
`ifdef MUTANT_IRQ_MASK
  assign irq = |irq_sts_q;                                                   // MUTANT: enables ignored
`else
  assign irq = (irq_sts_q[IRQ_DONE] & ctrl_q[CTRL_IRQ_EN_DONE]) |
               (irq_sts_q[IRQ_SAT]  & ctrl_q[CTRL_IRQ_EN_SAT])  |
               (irq_sts_q[IRQ_ERR]  & ctrl_q[CTRL_IRQ_EN_ERR]);
`endif
endmodule : mlacc_csr
`endif
