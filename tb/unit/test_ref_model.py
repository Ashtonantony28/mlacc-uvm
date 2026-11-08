"""Unit tests for the reference model, operand classifiers and the known-issue waiver."""
from mlacc_tb.ref_model import expected
from mlacc_tb.coverage import lane_class, rqs_outcome
from mlacc_tb.scoreboard import known_issue
from mlacc_tb.stream_agents import CmdItem

M = (1 << 64) - 1
P8 = int("7f" * 8, 16)
N8 = int("80" * 8, 16)


def test_dot8_extremes():
    assert expected(0, P8, P8, 0) == (8 * 127 * 127, 0)
    assert expected(0, N8, N8, 0) == (8 * 128 * 128, 0)
    assert expected(0, P8, N8, 0) == ((-8 * 127 * 128) & M, 0)


def test_dot8u_and_su():
    assert expected(1, M, M, 0) == (8 * 255 * 255, 0)
    assert expected(2, M, M, 0) == ((-8 * 255) & M, 0)


def test_macc_wraps():
    assert expected(4, P8, P8, (1 << 63) - 1)[0] == ((1 << 63) - 1 + 8 * 127 * 127) & M


def test_rqs_round_half_up_and_sat():
    assert expected(5, 3, 1, 0) == (2, 0)                 # 1.5 -> 2
    assert expected(5, (-3) & M, 1, 0) == ((-1) & M, 0)   # -1.5 -> -1 (half-up)
    assert expected(5, 1000, 0, 0) == (127, 1)
    assert expected(5, (-1000) & M, 0, 0) == ((-128) & M, 1)


def test_illegal_ops_return_zero():
    for op in (3, 6, 7):
        assert expected(op, P8, P8, 5) == (0, 0)


def test_classifiers():
    assert lane_class(0) == "zero" and lane_class(M) == "all_ones"
    assert lane_class(P8) == "max_pos" and lane_class(N8) == "min_neg"
    assert rqs_outcome((1 << 63) - 1, 1) == "add_overflow"
    assert rqs_outcome(1000, 0) == "sat_pos"


def test_known_issue_signature():
    assert known_issue(CmdItem("c", 0, 5, (1 << 63) - 1, 1, 0)) == "VTX-RQS-001"
    assert known_issue(CmdItem("c", 0, 5, (1 << 63) - 2, 1, 0)) is None
    assert known_issue(CmdItem("c", 0, 5, (1 << 63) - 1, 0, 0)) is None
    assert known_issue(CmdItem("c", 0, 0, (1 << 63) - 1, 1, 0)) is None
