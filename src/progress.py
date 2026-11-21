"""Pipeline progress reporting + cancellation."""
import time


class Cancelled(Exception):
    pass


# (key, label shown to the user, share of the total bar)
STAGES = [
    ('parse', 'Parsing G-code', 0.04),
    ('geom', 'Thermal analysis', 0.48),
    ('overhang', 'Thermal analysis', 0.03),
    ('baseline', 'Thermal analysis', 0.02),
    ('opt', 'Optimizing', 0.11),
    ('travel', 'Optimizing', 0.01),
    ('reorder', 'Optimizing', 0.02),
    ('emit', 'Optimizing', 0.02),
    ('m73', 'Verifying', 0.07),
    ('verify', 'Verifying', 0.17),
    ('write', 'Writing', 0.03),
]
_START = {}
_acc = 0.0
for _k, _l, _w in STAGES:
    _START[_k] = (_acc, _w, _l)
    _acc += _w


class Progress:
    """Call p(key, frac) from the pipeline. Forwards (label, overall 0..1, detail) to `cb` at most
    every ~0.3 % / label change, and raises Cancelled when `cancel_flag()` returns True."""
    def __init__(self, cb=None, cancel_flag=None):
        self.cb = cb; self.cancel_flag = cancel_flag
        self.last = (-1.0, None); self.t0 = time.time(); self.overall = 0.0; self.label = 'Starting'

    def __call__(self, key, frac=0.0, detail=''):
        if self.cancel_flag is not None and self.cancel_flag():
            raise Cancelled()
        s, w, label = _START.get(key, (self.overall, 0.0, key))
        ov = min(1.0, s + w * max(0.0, min(1.0, frac)))
        self.overall, self.label = ov, label
        if self.cb and (label != self.last[1] or ov - self.last[0] >= 0.003 or frac >= 1.0):
            self.last = (ov, label)
            self.cb(label, ov, detail)


def noop(key, frac=0.0, detail=''):
    pass
