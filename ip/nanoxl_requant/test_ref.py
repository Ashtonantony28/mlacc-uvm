"""Fast checks (no simulator): ref.py equals NanoXL's numpy model on the committed
fixture, and the vendored RTL is still byte-identical with the pinned upstream."""
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ref  # noqa: E402


def test_ref_matches_nanoxl_numerics():
    fx = json.loads((HERE / "fixtures" / "c2_cases.json").read_text())
    assert len(fx["source"]["commit"]) == 40 and len(fx["cases"]) == 6000
    for acc, bias, mult, shift, out16, want in fx["cases"]:
        got, _ = ref.requant_lane(acc, bias, mult, shift, bool(out16))
        assert got == want, (acc, bias, mult, shift, out16)


def test_fixture_covers_ties_and_saturation():
    cases = json.loads((HERE / "fixtures" / "c2_cases.json").read_text())["cases"]
    assert sum(ref.is_tie(*c[:4]) for c in cases) > 100
    assert any(c[5] == 127 for c in cases) and any(c[5] == -32768 for c in cases)


def test_vendored_rtl_matches_upstream_pin():
    pins = dict(re.findall(r"\| rtl/(\S+) \| `([0-9a-f]{64})` \|", (HERE / "UPSTREAM.md").read_text()))
    assert set(pins) == {"srdhm.sv", "sat_counter.sv", "requant.sv"}
    for f, h in pins.items():
        assert hashlib.sha256((HERE / "rtl" / f).read_bytes()).hexdigest() == h, f
