# cocotb + Icarus build for MLACC. Usage:
#   make -C sim TEST=test_smoke [UVM_TEST=smoke_test] [SEED=1] [MUTANT=MUTANT_X]
SIM              ?= icarus
TOPLEVEL_LANG    ?= verilog
RTL              := $(abspath ../rtl)
VERILOG_SOURCES  := $(addprefix $(RTL)/,$(shell cat $(RTL)/files.f))
COCOTB_TOPLEVEL  := mlacc_top
TEST             ?= test_smoke
COCOTB_TEST_MODULES := $(TEST)
export PYTHONPATH := $(abspath ../tb):$(abspath ../tb/tests):$(PYTHONPATH)
COMPILE_ARGS     += -g2012 -I$(RTL)
ifdef MUTANT
COMPILE_ARGS     += -D$(MUTANT)
SIM_BUILD        := sim_build_$(MUTANT)
endif
ifdef SEED
export COCOTB_RANDOM_SEED := $(SEED)
endif
ifdef UVM_TEST
export COCOTB_TEST_FILTER := $(UVM_TEST)$$
endif
include $(shell cocotb-config --makefiles)/Makefile.sim
