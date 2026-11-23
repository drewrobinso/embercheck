"""G-code parsing, section/protection detection and kinematic time estimation
for Bambu Studio (and OrcaSlicer-style) G-code.  Pure Python, no dependencies."""
import math, re

FEATURES_PRINT = {
    'Outer wall', 'Inner wall', 'Overhang wall', 'Sparse infill', 'Internal solid infill',
    'Top surface', 'Bottom surface', 'Bridge', 'Internal Bridge', 'Gap infill',
    'Floating vertical shell', 'Support', 'Support interface', 'Support transition',
    'Ironing', 'Skirt', 'Brim'}
# features whose speed may be RAISED (never outer/visible surfaces, bridges, overhangs)
FEATURES_SPEEDUP = {'Inner wall', 'Sparse infill', 'Internal solid infill', 'Support', 'Support transition'}
# features whose speed may be LOWERED (thermal / overhang protection)
FEATURES_SLOWDOWN = FEATURES_PRINT - {'Ironing', 'Skirt', 'Brim'}
# features whose islands (chunks) may be re-ordered to shorten travel
FEATURES_REORDER = {'Sparse infill', 'Internal solid infill', 'Gap infill', 'Support'}
WALLS = {'Outer wall', 'Inner wall'}

_word = re.compile(r'([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))')
_fstrip = re.compile(r'\s*F[-+]?(?:\d+\.?\d*|\.\d+)')

def split_comment(line):
    i = line.find(';')
    return (line, '') if i < 0 else (line[:i], line[i:])

def parse_words(code):
    return {k.upper(): float(v) for k, v in _word.findall(code)}

class Line:
    __slots__ = ('i', 'text', 'kind', 'cmd', 'w', 'x0', 'y0', 'x', 'y', 'z', 'e', 'f', 'effF',
                 'accel', 'feature', 'width', 'opt', 'layer', 'length', 'fan', 'is_ext',
                 'is_travel', 'is_wipe', 'r_before', 'in_wipe', 'prot')
    def __init__(self, i, text):
        self.i = i; self.text = text; self.kind = 'other'; self.cmd = ''; self.w = None
        self.x0 = self.y0 = self.x = self.y = self.z = None; self.e = None; self.f = None
        self.effF = None; self.accel = None; self.feature = None; self.width = None; self.opt = False
        self.layer = -1; self.length = 0.0; self.fan = 0.0; self.is_ext = False
        self.is_travel = False; self.is_wipe = False; self.r_before = 0.0; self.in_wipe = False; self.prot = False

class UnsupportedGcode(Exception):
    pass

class GcodeFile:
    def __init__(self, text, progress=None):
        self.progress = progress
        self.raw_lines = text.splitlines(keepends=True)
        self.config = {}
        self._parse_config()
        self._parse()

    # ---------------- config block ----------------
    def _parse_config(self):
        inblk = False
        for t in self.raw_lines[:5000]:
            s = t.strip()
            if s == '; CONFIG_BLOCK_START': inblk = True; continue
            if s == '; CONFIG_BLOCK_END': break
            if inblk and s.startswith('; ') and ' = ' in s:
                k, v = s[2:].split(' = ', 1); self.config[k.strip()] = v.strip()
        if not self.config:  # Orca/Prusa put config at the end
            for t in self.raw_lines[-3000:]:
                s = t.strip()
                if s.startswith('; ') and ' = ' in s:
                    k, v = s[2:].split(' = ', 1); self.config.setdefault(k.strip(), v.strip())

    def cfg(self, key, default=None, idx=0, num=True):
        v = self.config.get(key)
        if v is None: return default
        parts = [p.strip() for p in v.split(',')]
        p = parts[idx] if idx < len(parts) else parts[0]
        if not num: return p
        p = p.rstrip('%').strip('"')
        try: return float(p)
        except ValueError: return default

    # ---------------- main parse ----------------
    def _parse(self):
        L = [Line(i, t) for i, t in enumerate(self.raw_lines)]
        self.lines = L
        n = len(L)
        start_gcode_end = None; end_start = None
        for ln in L:
            s = ln.text.strip()
            if s == '; MACHINE_START_GCODE_END' and start_gcode_end is None: start_gcode_end = ln.i
            elif s == '; MACHINE_END_GCODE_START': end_start = ln.i
        if end_start is None:
            for ln in L:
                if ln.text.strip() == '; EXECUTABLE_BLOCK_END': end_start = ln.i
        if end_start is None: end_start = n
        first_layer = None
        for ln in L[(start_gcode_end or 0):end_start]:
            if ln.text.startswith('; CHANGE_LAYER'):
                first_layer = ln.i; break
        if first_layer is None:
            raise UnsupportedGcode('No "; CHANGE_LAYER" markers found - is this Bambu Studio / OrcaSlicer G-code?')
        self.body_start, self.body_end = first_layer, end_start
        self.layer_starts = [ln.i for ln in L[first_layer:end_start] if ln.text.startswith('; CHANGE_LAYER')]
        self.layer_z = []; self.layer_h = []

        x = y = z = 0.0; F = 1800.0; accel = 10000.0; feature = None; width = 0.4; fan = 0.0
        rel_e = True; absxyz = True; r = 0.0
        # Retraction is tracked per filament path, the way Bambu Studio's G-code writer does it
        # (Extruder::retracted_slot_id): one slot per extruder from filament_map, or per hotend on
        # machines that handle hotends as extruders. On dual-nozzle printers (H2D, X2D) the old
        # nozzle stays parked retracted across a nozzle change and is only de-retracted when that
        # nozzle is used again, so a single shared counter would see the new nozzle as retracted.
        # Single-nozzle printers map every filament to slot 0, which is the old single counter.
        fil_map = self._int_list('filament_map')
        noz_map = self._int_list('filament_nozzle_map')
        hotend_slots = (self.cfg('handle_hotend_as_extruder', 0) or 0) >= 1
        def tool_slot(t, h):
            if hotend_slots:
                if h is not None and h >= 0: return int(h)
                if t < len(noz_map) and noz_map[t] >= 0: return noz_map[t]
            if t < len(fil_map) and fil_map[t] >= 1: return fil_map[t] - 1
            return 0
        slot = 0; parked = {}
        protect = None  # name of protected span
        in_wipe = False
        layer = -1; lz = 0.0; lh = 0.2
        next_layer = 0
        prog = self.progress; nn = max(1, len(L))
        for ln in L:
            if prog is not None and (ln.i & 32767) == 0:
                prog('parse', ln.i / nn)
            t = ln.text; s = t.strip()
            if next_layer < len(self.layer_starts) and ln.i == self.layer_starts[next_layer]:
                layer = next_layer; next_layer += 1
                self.layer_z.append(None); self.layer_h.append(None)
            if ln.i == end_start: layer = -1
            if ln.i == self.body_start: r = 0.0; parked = {}
            in_body = self.body_start <= ln.i < self.body_end
            ln.layer = layer if in_body else -1
            ln.r_before = r
            code, com = split_comment(t)
            code = code.strip()
            if com:
                cs = com[1:].strip()
                if cs.startswith('FEATURE:'): feature = cs[8:].strip()
                elif cs.startswith('LINE_WIDTH:'):
                    try: width = float(cs[11:])
                    except ValueError: pass
                elif cs.startswith('Z_HEIGHT:') and in_body and layer >= 0:
                    try: self.layer_z[layer] = float(cs[9:])
                    except ValueError: pass
                elif cs.startswith('LAYER_HEIGHT:') and in_body and layer >= 0:
                    try: self.layer_h[layer] = float(cs[13:])
                    except ValueError: pass
                elif cs == 'WIPE_START': in_wipe = True
                elif cs == 'WIPE_END': in_wipe = False
                elif cs == 'SKIPPABLE_START': protect = 'skippable'
                elif cs.startswith('===== machine:') or cs.startswith('=====machine:'): protect = protect or 'machine_template'
                elif cs.startswith('filament end gcode'): protect = protect or 'filament_change'
            ln.feature = feature; ln.width = width
            if code:
                cmd = code.split()[0].upper(); ln.cmd = cmd
                if cmd in ('G0', 'G1', 'G2', 'G3'):
                    w = parse_words(code[len(cmd):]); ln.w = w; ln.kind = 'motion'
                    ln.x0, ln.y0 = x, y
                    nx = w.get('X', x) if absxyz else x + w.get('X', 0)
                    ny = w.get('Y', y) if absxyz else y + w.get('Y', 0)
                    nz = w.get('Z', z) if absxyz else z + w.get('Z', 0)
                    if 'F' in w: F = w['F']; ln.f = w['F']
                    if cmd in ('G2', 'G3') and ('I' in w or 'J' in w):
                        ln.length = arc_length(x, y, nx, ny, w.get('I', 0), w.get('J', 0), cmd == 'G2', w.get('P', 0))
                    else:
                        ln.length = math.hypot(nx - x, ny - y)
                    dz = abs(nz - z)
                    ln.x, ln.y, ln.z = nx, ny, nz
                    if 'E' in w:
                        ln.e = w['E']
                    ln.effF = F; ln.accel = accel
                    has_xy = math.hypot(nx - x, ny - y) > 1e-9
                    ln.r_before = r
                    if ln.e is not None and ln.e > 0 and has_xy:
                        ln.is_ext = True
                    elif ln.e is not None and ln.e < 0 and has_xy:
                        ln.is_wipe = True
                    elif has_xy and (ln.e is None or ln.e == 0):
                        ln.is_travel = True
                    if not has_xy and cmd in ('G0', 'G1'): ln.length = max(ln.length, dz)
                    if ln.e is not None and not ln.is_ext:
                        r += ln.e
                    if ln.is_ext:
                        r = 0.0 if abs(r) < 2e-3 else r
                    x, y, z = nx, ny, nz
                elif cmd == 'M106':
                    w = parse_words(code[4:]); ln.w = w
                    if 'P' not in w or int(w['P']) in (0, 1):
                        ln.kind = 'fan'; fan = w.get('S', 255.0)
                elif cmd == 'M107':
                    ln.kind = 'fan'; fan = 0.0; ln.w = {'S': 0.0}
                elif cmd == 'M204':
                    w = parse_words(code[4:]); ln.w = w; ln.kind = 'accel'
                    accel = w.get('S', w.get('P', accel))
                elif cmd == 'M83': rel_e = True
                elif cmd == 'M82':
                    rel_e = False
                    if in_body: raise UnsupportedGcode('Absolute extrusion (M82) inside print body - enable relative E (Bambu default).')
                elif cmd == 'G91':
                    absxyz = False
                    if in_body and protect is None: raise UnsupportedGcode('Relative positioning (G91) in print body is not supported.')
                elif cmd == 'G90': absxyz = True
                elif cmd == 'G92':
                    w = parse_words(code[3:])
                    if 'X' in w or 'Y' in w or 'Z' in w:
                        if in_body and protect is None: raise UnsupportedGcode('G92 XYZ offset in print body is not supported.')
                elif cmd[:1] == 'T' and cmd[1:].isdigit():
                    t = int(cmd[1:])
                    if t < 255:  # T255/T1000/T65535 etc. are firmware/maintenance codes, not filament selects
                        w = parse_words(code[len(cmd):])
                        ns = tool_slot(t, w.get('H'))
                        if ns != slot:
                            parked[slot] = r; slot = ns; r = parked.pop(ns, 0.0)
                elif cmd in ('M620',) and code.upper().startswith('M620 S'):
                    protect = protect or 'filament_change'
                elif cmd == 'M622':
                    protect = protect or 'm622'
                ln.fan = fan
                ln.in_wipe = in_wipe
            else:
                ln.fan = fan; ln.in_wipe = in_wipe
            ln.prot = protect is not None
            ln.opt = (in_body and protect is None and feature in FEATURES_PRINT and not in_wipe
                      and ln.layer >= 0)
            # span terminators (line itself still protected)
            if code and protect is not None:
                if ln.cmd == 'M621' and protect in ('filament_change', 'machine_template'):
                    protect = None
                elif ln.cmd == 'M623' and protect == 'm622':
                    protect = None
            if com and protect == 'skippable' and com[1:].strip() == 'SKIPPABLE_END':
                protect = None
        if not rel_e:
            raise UnsupportedGcode('G-code ends in absolute extrusion mode; relative E (M83) required.')
        # fill missing layer z
        lastz = 0.0
        for k in range(len(self.layer_starts)):
            if self.layer_z[k] is None: self.layer_z[k] = lastz + (self.layer_h[k] or 0.2)
            if self.layer_h[k] is None: self.layer_h[k] = self.layer_z[k] - lastz
            lastz = self.layer_z[k]

    def _int_list(self, key):
        v = self.config.get(key)
        if not v: return []
        out = []
        for p in v.replace(';', ',').split(','):
            try: out.append(int(float(p.strip().strip('"'))))
            except ValueError: return []
        return out

    def layer_range(self, k):
        a = self.layer_starts[k]
        b = self.layer_starts[k + 1] if k + 1 < len(self.layer_starts) else self.body_end
        return a, b

    def protected_signature(self):
        return [ln.text for ln in self.lines if not ln.opt and ln.layer >= 0 and ln.kind != 'motion' and ln.kind != 'fan'
                and not ln.text.startswith('M73 P')]


def arc_length(x0, y0, x1, y1, i, j, cw, turns=0):
    cx, cy = x0 + i, y0 + j
    rr = math.hypot(i, j)
    a0 = math.atan2(y0 - cy, x0 - cx); a1 = math.atan2(y1 - cy, x1 - cx)
    if cw:
        d = a0 - a1
    else:
        d = a1 - a0
    while d <= 1e-9: d += 2 * math.pi
    if abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9: d = 2 * math.pi
    d += 2 * math.pi * max(0, int(turns) - 1)
    return rr * d


# ---------------- kinematics ----------------
def seg_time(L, v, a, v0, v1):
    if L <= 0: return 0.0
    if v <= 0: return 0.0
    if a <= 0: return L / v
    v0 = min(v0, v); v1 = min(v1, v)
    da = (v * v - v0 * v0) / (2 * a); dd = (v * v - v1 * v1) / (2 * a)
    if da + dd <= L:
        return (v - v0) / a + (v - v1) / a + (L - da - dd) / v
    vp2 = (2 * a * L + v0 * v0 + v1 * v1) / 2
    vp = math.sqrt(max(vp2, 0))
    if vp < max(v0, v1):
        return 2 * L / (v0 + v1) if (v0 + v1) > 0 else L / v
    return (vp - v0) / a + (vp - v1) / a

def dwell_time(ln):
    if ln.cmd == 'G4' and ln.w is None:
        code = split_comment(ln.text)[0]
        w = parse_words(code[2:])
        return w.get('P', 0) / 1000.0 + w.get('S', 0)
    if ln.cmd == 'M400':
        code = split_comment(ln.text)[0]
        w = parse_words(code[4:])
        return w.get('P', 0) / 1000.0 + w.get('S', 0)
    return 0.0

class Kinematics:
    def __init__(self, g):
        self.vmax_xy = (g.cfg('machine_max_speed_x', 500) or 500)
        self.vmax_z = (g.cfg('machine_max_speed_z', 20) or 20)
        self.vmax_e = (g.cfg('machine_max_speed_e', 30) or 30)
        self.amax = (g.cfg('machine_max_acceleration_extruding', 20000) or 20000)
        self.amax_travel = (g.cfg('machine_max_acceleration_travel', 0) or 0) or self.amax
        self.amax_z = g.cfg('machine_max_acceleration_z', 500) or 500
        self.jerk = g.cfg('machine_max_jerk_x', 9) or 9

def line_dir(ln):
    if ln.kind != 'motion' or ln.length <= 1e-9 or ln.x is None: return None
    dx, dy = ln.x - ln.x0, ln.y - ln.y0
    d = math.hypot(dx, dy)
    if d < 1e-9: return None
    return (dx / d, dy / d)

def estimate_times(lines, kin, feed_of=None, accel_of=None):
    """Return list of per-line durations (seconds). feed_of(ln)->F mm/min overrides effF, accel_of(ln)->mm/s2 overrides
    the modal M204 acceleration."""
    n = len(lines)
    out = [0.0] * n
    speeds = [0.0] * n; dirs = [None] * n
    for k, ln in enumerate(lines):
        if ln.kind == 'motion':
            F = feed_of(ln) if feed_of else ln.effF
            v = (F or 1800) / 60.0
            if ln.length > 1e-9 and ln.x is not None and (math.hypot(ln.x - ln.x0, ln.y - ln.y0) > 1e-9 or ln.cmd in ('G2', 'G3')):
                v = min(v, kin.vmax_xy)
            elif ln.z is not None and ln.e is None:
                v = min(v, kin.vmax_z)
            else:
                v = min(v, kin.vmax_e)
            speeds[k] = v; dirs[k] = line_dir(ln)
    prev_k = None
    vj_in = [0.0] * n
    for k in range(n):
        ln = lines[k]
        if ln.kind != 'motion': continue
        if prev_k is not None and dirs[k] is not None and dirs[prev_k] is not None:
            c = dirs[k][0] * dirs[prev_k][0] + dirs[k][1] * dirs[prev_k][1]
            vj = max(kin.jerk, min(speeds[k], speeds[prev_k]) * max(0.0, c))
            vj_in[k] = min(vj, speeds[k], speeds[prev_k])
        else:
            vj_in[k] = min(kin.jerk, speeds[k])
        prev_k = k
    nxt = None
    vj_out = [0.0] * n
    for k in range(n - 1, -1, -1):
        if lines[k].kind != 'motion': continue
        vj_out[k] = vj_in[nxt] if nxt is not None else min(kin.jerk, speeds[k])
        nxt = k
    for k, ln in enumerate(lines):
        if ln.kind == 'motion':
            a = (accel_of(ln) if accel_of else ln.accel) or kin.amax
            a = min(a, kin.amax if ln.is_ext else kin.amax_travel)
            if not (ln.length > 1e-9 and (dirs[k] is not None or ln.cmd in ('G2', 'G3'))):
                a = kin.amax_z if (ln.e is None) else 5000
            out[k] = seg_time(ln.length, speeds[k], a, vj_in[k], vj_out[k])
        elif ln.cmd in ('G4', 'M400'):
            out[k] = dwell_time(ln)
    return out, speeds
