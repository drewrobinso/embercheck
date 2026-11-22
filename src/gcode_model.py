"""G-code parsing, section/protection detection and kinematic time estimation
for Bambu Studio (and OrcaSlicer-style) G-code and, since 1.5, PrusaSlicer G-code for Marlin printers.
Pure Python, no dependencies.

Each file is read through a dialect (see BAMBU / PRUSA below): the dialect knows the slicer's comment markers
(feature, layer change, wipe, line width) and how to write an acceleration command for the firmware. PrusaSlicer
feature names are mapped onto the internal (Bambu) feature names, so the optimizer itself is slicer-neutral."""
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


class Dialect:
    """Comment markers and firmware commands of one slicer. The Bambu values are exactly what 1.4.x used."""
    name = 'bambu'
    slicer = 'Bambu Studio'
    feature = '; FEATURE:'          # feature change comment (prefix)
    layer = '; CHANGE_LAYER'        # layer change comment (prefix)
    wipe_start = '; WIPE_START'
    wipe_end = '; WIPE_END'
    wipe_prefix = '; WIPE_'
    width_key = 'LINE_WIDTH:'       # substring of the line-width comment
    width_fmt = '; LINE_WIDTH: %g\n'
    accel_fmt = 'M204 S%d\n'        # acceleration for printing moves
    f_only_in_wipe = False          # PrusaSlicer starts each wipe with a bare "G1 F..." line
    flavor = 'bambu'


BAMBU = Dialect()


class PrusaDialect(Dialect):
    name = 'prusaslicer'
    slicer = 'PrusaSlicer'
    feature = ';TYPE:'
    layer = ';LAYER_CHANGE'
    wipe_start = ';WIPE_START'
    wipe_end = ';WIPE_END'
    wipe_prefix = ';WIPE_'
    width_key = 'WIDTH:'
    width_fmt = ';WIDTH:%g\n'
    f_only_in_wipe = True

    def __init__(self, flavor='marlin2'):
        self.flavor = flavor
        # Marlin 2 (PrusaSlicer "marlin2"): M204 P = printing, T = travel, R = retract; legacy Marlin / Klipper: M204 S
        self.accel_fmt = 'M204 P%d\n' if flavor == 'marlin2' else 'M204 S%d\n'


# PrusaSlicer ;TYPE: names (ExtrusionRole, GCodeProcessor) -> internal feature names
PRUSA_FEATURES = {
    'External perimeter': 'Outer wall', 'Perimeter': 'Inner wall', 'Overhang perimeter': 'Overhang wall',
    'Internal infill': 'Sparse infill', 'Solid infill': 'Internal solid infill', 'Top solid infill': 'Top surface',
    'Bridge infill': 'Bridge', 'Gap fill': 'Gap infill', 'Skirt/Brim': 'Skirt', 'Skirt': 'Skirt', 'Brim': 'Brim',
    'Support material': 'Support', 'Support material interface': 'Support interface', 'Ironing': 'Ironing',
    'Wipe tower': 'Prime tower', 'Custom': 'Custom'}
# firmware flavours whose motion/acceleration commands EmberCheck writes correctly
PRUSA_FLAVORS = ('marlin2', 'marlin', 'klipper')
# PrusaSlicer config keys -> the internal (Bambu) names the optimizer reads (only used when the Bambu key is absent)
PRUSA_ALIASES = {
    'machine_max_speed_x': 'machine_max_feedrate_x', 'machine_max_speed_y': 'machine_max_feedrate_y',
    'machine_max_speed_z': 'machine_max_feedrate_z', 'machine_max_speed_e': 'machine_max_feedrate_e',
    'nozzle_temperature': 'temperature', 'fan_max_speed': 'max_fan_speed', 'fan_min_speed': 'min_fan_speed',
    'overhang_fan_speed': 'bridge_fan_speed', 'close_fan_the_first_x_layers': 'disable_fan_first_layers',
    'slow_down_layer_time': 'slowdown_below_layer_time', 'slow_down_min_speed': 'min_print_speed',
    'retraction_length': 'retract_length', 'retraction_speed': 'retract_speed', 'deretraction_speed': 'deretract_speed',
    'resolution': 'gcode_resolution', 'chamber_temperatures': 'chamber_temperature', 'z_hop': 'retract_lift'}
# single lines PrusaSlicer may put in the print body that must never move or change (colour change, pause, tool
# change, object labels for the firmware, user messages)
PRUSA_PROTECTED_CMDS = ('M600', 'M601', 'M0', 'M1', 'M25', 'M125', 'M486', 'M117', 'M118', 'M240', 'M701', 'M702')


def detect_dialect(raw_lines):
    """PrusaSlicer if its header ("; generated by PrusaSlicer") or its config block is present, else Bambu."""
    for t in raw_lines[:60]:
        if t.startswith('; generated by PrusaSlicer'):
            return 'prusaslicer'
    for t in raw_lines[-500:]:
        if t.startswith('; prusaslicer_config = '):
            return 'prusaslicer'
    return 'bambu'


class GcodeFile:
    def __init__(self, text, progress=None):
        self.progress = progress
        if text[:4] == 'GCDE':
            raise UnsupportedGcode('Binary G-code (.bgcode) is not supported - in PrusaSlicer turn off Printer Settings > '
                                   'General > Firmware > "Supports binary G-code", or use plain .gcode.')
        self.raw_lines = text.splitlines(keepends=True)
        self.config = {}
        self.slicer_time = None
        if detect_dialect(self.raw_lines) == 'prusaslicer':
            self._parse_config_prusa()
            self._parse_prusa()
        else:
            self.dialect = BAMBU
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
            if ln.i == self.body_start: r = 0.0
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

    # ---------------- PrusaSlicer ----------------
    def _parse_config_prusa(self):
        """'; prusaslicer_config = begin' ... '= end' at the end of the file, plus the slicer's own time estimate."""
        inblk = False
        tail = self.raw_lines[-6000:]
        for t in tail:
            s = t.strip()
            if s == '; prusaslicer_config = begin': inblk = True; continue
            if s == '; prusaslicer_config = end': break
            if inblk and s.startswith('; ') and ' = ' in s:
                k, v = s[2:].split(' = ', 1); self.config[k.strip()] = v.strip()
            elif not inblk and s.startswith('; estimated printing time (normal mode) = '):
                self.slicer_time = s.split(' = ', 1)[1].strip()
        c = self.config
        if 'gcode_resolution' in c:     # PrusaSlicer's "resolution" is the slicing resolution, not the G-code one
            c['resolution'] = c['gcode_resolution']
        for ours, theirs in PRUSA_ALIASES.items():
            if ours not in c and theirs in c:
                c[ours] = c[theirs]
        if 'enable_arc_fitting' not in c and 'arc_fitting' in c:
            c['enable_arc_fitting'] = '0' if c['arc_fitting'].strip().lower() in ('disabled', '0', '') else '1'
        # 0 = no limit in PrusaSlicer; the print profile's max_volumetric_speed applies when the filament has none
        try:
            if float(self.cfg('filament_max_volumetric_speed', 0) or 0) <= 0 and (self.cfg('max_volumetric_speed', 0) or 0) > 0:
                c['filament_max_volumetric_speed'] = c['max_volumetric_speed']
        except (TypeError, ValueError):
            pass
        flavor = (c.get('gcode_flavor') or 'marlin2').strip().lower()
        self.dialect = PrusaDialect(flavor)
        if flavor not in PRUSA_FLAVORS:
            raise UnsupportedGcode('PrusaSlicer G-code flavor "%s" is not supported yet (supported: Marlin 2, Marlin legacy, '
                                   'Klipper) - Printer Settings > General > Firmware > G-code flavor.' % flavor)
        if str(c.get('use_relative_e_distances', '1')).strip() not in ('1', 'true'):
            raise UnsupportedGcode('Absolute extrusion - in PrusaSlicer turn on Printer Settings > General > Advanced > '
                                   '"Use relative E distances" (EmberCheck needs relative E, M83).')
        if str(c.get('use_firmware_retraction', '0')).strip() in ('1', 'true'):
            raise UnsupportedGcode('Firmware retraction (G10/G11) is not supported yet - turn off Printer Settings > '
                                   'General > Advanced > "Use firmware retraction".')
        if str(c.get('spiral_vase', '0')).strip() in ('1', 'true'):
            raise UnsupportedGcode('Spiral vase mode is not supported (every move changes Z).')

    def _parse_prusa(self):
        L = [Line(i, t) for i, t in enumerate(self.raw_lines)]
        self.lines = L
        n = len(L)
        D = self.dialect
        self.layer_starts = [ln.i for ln in L if ln.text.startswith(D.layer)]
        if not self.layer_starts:
            raise UnsupportedGcode('No ";LAYER_CHANGE" markers found - is this PrusaSlicer G-code?')
        first_layer = self.layer_starts[0]
        # end of the print body: the end G-code (';TYPE:Custom' after the last extrusion), else the footer
        last_ext = None
        for ln in reversed(L):
            t = ln.text
            if t.startswith('G1 ') or t.startswith('G2 ') or t.startswith('G3 '):
                w = parse_words(split_comment(t)[0][2:])
                if w.get('E', 0) > 0 and ('X' in w or 'Y' in w):
                    last_ext = ln.i; break
        if last_ext is None or last_ext < first_layer:
            raise UnsupportedGcode('No extrusion moves found after the first ";LAYER_CHANGE".')
        end_start = None
        for ln in L[last_ext:]:
            s = ln.text.strip()
            if s == ';TYPE:Custom':
                end_start = ln.i; break
            if s.startswith('; filament used') or s.startswith('; objects_info') or s.startswith('; prusaslicer_config'):
                end_start = ln.i; break
        if end_start is None: end_start = n
        self.body_start, self.body_end = first_layer, end_start
        self.layer_starts = [i for i in self.layer_starts if i < end_start]
        self.layer_z = []; self.layer_h = []

        x = y = z = 0.0; F = 1800.0; accel = 1000.0; feature = None; width = 0.4; fan = 0.0
        rel_e = True; absxyz = True; r = 0.0
        protect = None
        in_wipe = False
        layer = -1
        next_layer = 0
        prog = self.progress; nn = max(1, len(L))
        for ln in L:
            if prog is not None and (ln.i & 32767) == 0:
                prog('parse', ln.i / nn)
            t = ln.text
            new_layer = next_layer < len(self.layer_starts) and ln.i == self.layer_starts[next_layer]
            if new_layer:
                layer = next_layer; next_layer += 1
                self.layer_z.append(None); self.layer_h.append(None)
                # the layer change (retract, wipe, Z move, travel, the user's layer G-code) belongs to no feature
                feature = None
                if protect == 'custom': protect = None
            if ln.i == end_start: layer = -1
            if ln.i == self.body_start: r = 0.0
            in_body = self.body_start <= ln.i < self.body_end
            ln.layer = layer if in_body else -1
            ln.r_before = r
            code, com = split_comment(t)
            code = code.strip()
            if com:
                cs = com[1:].strip()
                if t.startswith(D.feature):
                    raw = t[len(D.feature):].strip()
                    feature = PRUSA_FEATURES.get(raw, raw)
                    if in_body and raw == 'Custom': protect = 'custom'      # colour change / pause / custom G-code
                    elif protect == 'custom': protect = None
                elif cs.startswith('WIDTH:'):
                    try: width = float(cs[6:])
                    except ValueError: pass
                elif cs.startswith('Z:') and in_body and layer >= 0 and self.layer_z[layer] is None:
                    try: self.layer_z[layer] = float(cs[2:])
                    except ValueError: pass
                elif cs.startswith('HEIGHT:') and in_body and layer >= 0 and self.layer_h[layer] is None:
                    try: self.layer_h[layer] = float(cs[7:])
                    except ValueError: pass
                elif cs == 'WIPE_START': in_wipe = True
                elif cs == 'WIPE_END': in_wipe = False
            ln.feature = feature; ln.width = width
            line_prot = False
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
                    w = parse_words(code[4:]); ln.w = w
                    if 'S' in w or 'P' in w:          # "M204 T.." (travel) / "M204 R.." (retract) only: not ours
                        ln.kind = 'accel'
                        accel = w.get('S', w.get('P', accel))
                elif cmd == 'M83': rel_e = True
                elif cmd == 'M82':
                    rel_e = False
                    if in_body: raise UnsupportedGcode('Absolute extrusion (M82) inside the print body - turn on "Use relative E distances" in PrusaSlicer.')
                elif cmd == 'G91':
                    absxyz = False
                    if in_body and protect is None: raise UnsupportedGcode('Relative positioning (G91) in the print body is not supported.')
                elif cmd == 'G90': absxyz = True
                elif cmd == 'G92':
                    w = parse_words(code[3:])
                    if 'X' in w or 'Y' in w or 'Z' in w:
                        if in_body and protect is None: raise UnsupportedGcode('G92 XYZ offset in the print body is not supported.')
                elif cmd == 'G10' or cmd == 'G11':
                    if in_body: raise UnsupportedGcode('Firmware retraction (G10/G11) is not supported yet.')
                elif cmd in PRUSA_PROTECTED_CMDS or (cmd.startswith('T') and cmd[1:].isdigit()):
                    line_prot = True
                ln.fan = fan
                ln.in_wipe = in_wipe
            else:
                ln.fan = fan; ln.in_wipe = in_wipe
            ln.prot = protect is not None or line_prot
            ln.opt = (in_body and not ln.prot and feature in FEATURES_PRINT and not in_wipe and ln.layer >= 0)
        if not rel_e:
            raise UnsupportedGcode('G-code ends in absolute extrusion mode; relative E (M83) required.')
        lastz = 0.0
        for k in range(len(self.layer_starts)):
            if self.layer_z[k] is None: self.layer_z[k] = lastz + (self.layer_h[k] or 0.2)
            if self.layer_h[k] is None: self.layer_h[k] = self.layer_z[k] - lastz
            lastz = self.layer_z[k]

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
