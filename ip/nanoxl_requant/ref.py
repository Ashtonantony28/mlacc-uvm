"""Pure-int reference for NanoXL contract C2 (requant), one lane at a time.

    x   = wrap32(acc + bias)
    y   = RoundingDivideByPOT(SRDHM(x, mult), shift)      gemmlowp semantics
    out = clamp(y, int8 or int16)

Restated from nanoxl/numerics.py; fixtures/c2_cases.json (made by NanoXL's own numpy
model, see gen_fixture.py) pins it. Valid for any int32 mult; NanoXL's contract
function additionally requires mult in [2^30, 2^31).
"""
INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1


def wrap32(v):
    return ((v + (1 << 31)) % (1 << 32)) - (1 << 31)


def srdhm(a, b):
    if a == INT32_MIN and b == INT32_MIN:
        return INT32_MAX
    ab = a * b
    s = ab + ((1 << 30) if ab >= 0 else 1 - (1 << 30))
    return s >> 31 if s >= 0 else -((-s) >> 31)          # C-style truncation


def rdivpot(x, e):
    mask = (1 << e) - 1
    rem = x & mask
    thr = (mask >> 1) + (1 if x < 0 else 0)
    return (x >> e) + (1 if rem > thr else 0)


def requant_lane(acc, bias, mult, shift, out16):
    """Returns (out, saturated)."""
    y = rdivpot(srdhm(wrap32(acc + bias), mult), shift)
    lo, hi = (-32768, 32767) if out16 else (-128, 127)
    return min(max(y, lo), hi), (y < lo or y > hi)


def is_tie(acc, bias, mult, shift):
    """True if the rdivpot step lands exactly halfway (the rounding rule decides)."""
    if shift == 0:
        return False
    q = srdhm(wrap32(acc + bias), mult)
    return (q & ((1 << shift) - 1)) == (1 << (shift - 1))
