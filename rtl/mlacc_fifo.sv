// mlacc_fifo.sv — synchronous FIFO, power-of-two depth, registered outputs.
`ifndef MLACC_FIFO_SV
`define MLACC_FIFO_SV
module mlacc_fifo #(
  parameter int unsigned WIDTH = 8,
  parameter int unsigned DEPTH = 4
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             push,
  input  logic [WIDTH-1:0] wdata,
  input  logic             pop,
  output logic [WIDTH-1:0] rdata,
  output logic             empty,
  output logic             full,
  output logic [$clog2(DEPTH):0] count
);
  localparam int unsigned AW = $clog2(DEPTH);

  logic [WIDTH-1:0] mem [DEPTH];
  logic [AW-1:0]    wptr, rptr;

  assign empty = (count == 0);
  assign full  = (count == (AW+1)'(DEPTH));
  assign rdata = mem[rptr];

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      wptr  <= '0;
      rptr  <= '0;
      count <= '0;
    end else begin
      if (push) begin
        mem[wptr] <= wdata;
        wptr      <= wptr + 1'b1;
      end
      if (pop) rptr <= rptr + 1'b1;
      count <= count + (AW+1)'(push) - (AW+1)'(pop);
    end
  end
endmodule : mlacc_fifo
`endif
