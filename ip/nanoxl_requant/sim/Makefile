# cocotb + Icarus build for NanoXL requant.sv under the pyuvm bench.
#   make -C ip/nanoxl_requant/sim UVM_TEST=random_test SEED=1 [RTL_DIR=<patched copy>] [SIM_BUILD=...]
SIM             ?= icarus
TOPLEVEL_LANG   ?= verilog
RTL_DIR         ?= $(abspath ../rtl)
VERILOG_SOURCES := $(RTL_DIR)/srdhm.sv $(RTL_DIR)/sat_counter.sv $(RTL_DIR)/requant.sv
COCOTB_TOPLEVEL := requant
COCOTB_TEST_MODULES := rq_tb
NDSP            ?= 4
COMPILE_ARGS    += -g2012 -Prequant.L=4 -Prequant.NDSP=$(NDSP)
export PYTHONPATH := $(abspath ../tb):$(PYTHONPATH)
export RQ_L := 4
ifdef SEED
export COCOTB_RANDOM_SEED := $(SEED)
endif
ifdef UVM_TEST
export COCOTB_TEST_FILTER := $(UVM_TEST)$$
endif
include $(shell cocotb-config --makefiles)/Makefile.sim
