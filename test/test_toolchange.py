"""Retraction tracking across nozzle / filament changes (GitHub issue #1, X2D aux nozzle).
Run: python test/test_toolchange.py

Bambu Studio parks retraction per filament path (Extruder::retracted_slot_id): per extruder from filament_map, or per
hotend on machines with handle_hotend_as_extruder. On the H2D / X2D the old nozzle is left retracted (-2 mm toolchange
retract) when the other nozzle takes over and is only de-retracted when it is used again. A single shared counter saw
the new nozzle as 'extruding while retracted (-2.000)' and refused every file that switched to the second nozzle.

The fixture is real Bambu Studio 02.09.01.70 CLI output for an X2D 0.4 (stock profiles from the v02.09.01.70 tag):
a 15 mm box in PETG, filament 1 on the main nozzle, filament 2 on the aux nozzle from z=4 mm, back to main at z=8 mm."""
import gzip, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))
from gcode_model import GcodeFile
from optimizer import Settings
import embercheck as ec

FAILS = []


def check(name, cond):
    print('%-70s %s' % (name, 'ok' if cond else 'FAIL'))
    if not cond: FAILS.append(name)


def gfile(body, filament_map=None, handle_hotend=None, nozzle_map=None):
    cfg = ['; CONFIG_BLOCK_START']
    if filament_map is not None: cfg.append('; filament_map = %s' % filament_map)
    if nozzle_map is not None: cfg.append('; filament_nozzle_map = %s' % nozzle_map)
    if handle_hotend is not None: cfg.append('; handle_hotend_as_extruder = %d' % handle_hotend)
    cfg.append('; CONFIG_BLOCK_END')
    head = ['; HEADER_BLOCK_START', '; HEADER_BLOCK_END'] + cfg + ['M83', 'T0 H-1', '; MACHINE_START_GCODE_END',
                                                                   '; CHANGE_LAYER', '; Z_HEIGHT: 0.2', '; FEATURE: Inner wall']
    tail = ['; MACHINE_END_GCODE_START', 'M400']
    return GcodeFile('\n'.join(head + body.strip().splitlines() + tail) + '\n')


def retracted_extrusions(g):
    return [round(l.r_before, 3) for l in g.lines if l.is_ext and l.layer >= 0 and abs(l.r_before) > 2e-3]


# the sequence Bambu Studio writes for a nozzle change (shape taken from the real X2D slice, change block shortened)
SWITCH = """
G1 X10 Y10 E.5
G1 E-.4 F1800
G1 E-1.6
; filament end gcode
M620 S1A B H-1
M620.11 P0 I0 B-1 E0
T1 H-1
M621 S1A
; filament start gcode
G1 E-.4 F1800
G1 E.4 F1800
G1 X20 Y10 E.5
G1 E-.4 F1800
G1 E-1.6
; filament end gcode
M620 S0A B H-1
T0 H-1
M621 S0A
; filament start gcode
G1 E2 F1800
G1 X20 Y20 E.5
"""

# --- dual nozzle: per-extruder parking (the bug) ---
g = gfile(SWITCH, filament_map='1,2')
check('X2D main->aux->main: no extrusion seen as retracted', retracted_extrusions(g) == [])

# --- single nozzle (filament_map all 1 / missing): exactly the old single counter ---
g = gfile(SWITCH, filament_map='1,1')
check('same nozzle (filament_map 1,1): old shared counter, both later parts flagged', retracted_extrusions(g) == [-2.0, -2.0])
g = gfile(SWITCH)
check('no filament_map (X1/P1/A1, Orca): old shared counter', retracted_extrusions(g) == [-2.0, -2.0])
AMS = """
G1 X10 Y10 E.5
G1 E-.4 F1800
G1 E-1.6
; filament end gcode
M620 S1A
T1
M621 S1A
; filament start gcode
G1 E2 F1800
G1 X20 Y10 E.5
"""
g = gfile(AMS, filament_map='1,1,1,1')
check('AMS filament change on one nozzle with matching de-retract: clean', retracted_extrusions(g) == [])

# --- safety is not weakened: real retraction errors are still caught on either nozzle ---
g = gfile(SWITCH.replace('G1 E2 F1800\n', ''), filament_map='1,2')
check('back on main nozzle without its de-retract: flagged (-2)', retracted_extrusions(g) == [-2.0])
g = gfile(SWITCH.replace('G1 E-.4 F1800\nG1 E.4 F1800\nG1 X20 Y10', 'G1 E-.4 F1800\nG1 X20 Y10'), filament_map='1,2')
check('aux nozzle extrudes after its own retract: flagged (-0.4)', retracted_extrusions(g)[:1] == [-0.4])
g = gfile(SWITCH.replace('G1 E2 F1800\n', 'G1 E2.5 F1800\n'), filament_map='1,2')
check('main nozzle over-de-retracted: flagged (+0.5)', retracted_extrusions(g) == [0.5])
g = gfile(SWITCH.replace('T1 H-1', 'T1000 H-1'), filament_map='1,2')
check('T1000 / T65535 style maintenance codes do not switch the slot', retracted_extrusions(g) == [-2.0, -2.0])

# --- machines that handle hotends as extruders (H2C-style): slot = H word / filament_nozzle_map ---
g = gfile(SWITCH.replace('T1 H-1', 'T1 H1').replace('T0 H-1', 'T0 H0'), filament_map='1,1', handle_hotend=1)
check('hotend-as-extruder, H on the T line: per-hotend parking', retracted_extrusions(g) == [])
g = gfile(SWITCH, filament_map='1,1', handle_hotend=1, nozzle_map='0,1')
check('hotend-as-extruder, filament_nozzle_map fallback: per-hotend parking', retracted_extrusions(g) == [])
g = gfile(SWITCH.replace('T1 H-1', 'T1 H0'), filament_map='1,1', handle_hotend=1)
check('hotend-as-extruder, same hotend: shared slot, flagged', retracted_extrusions(g) == [-2.0, -2.0])

# --- end to end on the real X2D slice: every goal writes a file that passes the safety check ---
with gzip.open(os.path.join(HERE, 'fixtures', 'x2d_aux_nozzle_switch.gcode.gz'), 'rt', encoding='utf-8', newline='') as f:
    text = f.read()
g = GcodeFile(text)
check('fixture: X2D, switches to the aux nozzle and back',
      g.config.get('printer_model') == 'Bambu Lab X2D' and g.config.get('filament_map') == '1,2'
      and sum(1 for l in g.lines if l.cmd in ('T0', 'T1') and l.layer >= 0) == 2)
check('fixture: original has no extrusion seen as retracted', retracted_extrusions(g) == [])
for goal in ('quality', 'balanced', 'speed'):
    st = Settings(goal=goal, fix_strings=True); st.dry_run = False
    out, _html, summ = ec.process_text(text, st, 'x2d_aux_nozzle_switch.gcode', log=lambda *a: None)
    errs = (summ or {}).get('errors') if isinstance(summ, dict) else None
    check('fixture: %s goal writes optimised G-code (errors=%s)' % (goal, errs), out is not None and out != text)

print('%d failed' % len(FAILS) if FAILS else 'all ok')
sys.exit(1 if FAILS else 0)
