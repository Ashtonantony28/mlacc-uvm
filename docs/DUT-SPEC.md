# MLACC v1 — DUT specification

- Clock `clk`, active-low sync reset `rst_n`.
- **Pipeline:** cmd skid-register → stage-1 datapath (`vortex_xmlacc`, unchanged from Vortex-V)
  → stage-2 result register → **result FIFO (depth 4)**. Latency 2 cycles when not stalled.
  `cmd_ready` deasserts when the FIFO plus in-flight entries would overflow.
- Commands are ignored (ready=0) while `CTRL.EN=0`.
- **CSRs (APB, word aligned, 32-bit):**

| Addr | Name | Fields | Access |
|---|---|---|---|
| 0x000 | ID | `0x4D4C4143` ("MLAC") | RO |
| 0x004 | VERSION | `0x0001_0000` | RO |
| 0x008 | CTRL | [0] EN, [1] IRQ_EN_DONE, [2] IRQ_EN_SAT | RW |
| 0x00C | STATUS | [0] BUSY, [3:1] reserved, [7:4] FIFO_LEVEL | RO |
| 0x010 | MLSTAT | [0] SAT sticky (set by an `rqs` clamp) | W1C |
| 0x014 | IRQ_STATUS | [0] DONE (a result was accepted), [1] SAT | W1C |
| 0x018 | CMD_COUNT | [31:0] commands accepted since reset | RO |
| 0x01C | RSP_COUNT | [31:0] results delivered since reset | RO |
| 0x020 | SCRATCH | [31:0] | RW |
| other | — | reads 0, writes ignored, `PSLVERR=1` | — |

- `irq = (IRQ_STATUS.DONE & CTRL.IRQ_EN_DONE) | (IRQ_STATUS.SAT & CTRL.IRQ_EN_SAT)`.
- MLSTAT.SAT mirrors the Vortex-V CSR 0x801 semantics, so the ISS spec carries over.


## Pins

| Group | Signals |
|---|---|
| clock/reset | `clk`, `rst_n` (active-low, synchronous) |
| APB3 | `psel penable pwrite paddr[11:0] pwdata[31:0] prdata[31:0] pready pslverr` |
| command | `cmd_valid cmd_ready cmd_tag[7:0] cmd_op[2:0] cmd_rs1/rs2/rs3[63:0]` |
| result | `rsp_valid rsp_ready rsp_tag[7:0] rsp_result[63:0] rsp_sat` |
| interrupt | `irq` |

## Ops (`cmd_op`, = Vortex-V Xmlacc funct3)

| code | op | result |
|---|---|---|
| 0 | dot8 | SX64(Σ sext8(rs1[i])·sext8(rs2[i])) |
| 1 | dot8u | ZX64(Σ zext8·zext8) |
| 2 | dot8su | SX64(Σ sext8(rs1)·zext8(rs2)) |
| 4 | macc | rs3 + Σ sext8·sext8 (64-bit wrap) |
| 5 | rqs | clamp_int8((rs1 + 2^(sh-1)) >>s sh), sh = rs2[5:0]; `rsp_sat`=1 if clamped |
| 3, 6, 7 | illegal | result 0, sat 0, IRQ_STATUS.ERR set |

Timing: a W1C write and a hardware set of the same bit in the same cycle leave the bit set.
DONE is set when a result is handed over (`rsp_valid && rsp_ready`); SAT/ERR are set the
cycle the command is in stage 1.
