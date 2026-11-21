# Safety checks and tests

## Built-in validator (every run, before the file is written)
The new G-code is parsed again and compared with the original. Any failure means **the original G-code is kept** and the card/report say why.
- same layer count; start G-code, end G-code and every protected block (AMS M620/M621, firmware M622/M623 conditionals, timelapse) byte-identical; temperature commands identical
- per layer: exact extrusion sum, and the same extrusion moves (with Z); arcs are expanded back into the original segments
- no extruding while retracted; feeds within machine limits; flow under the filament limit
- acceleration: only planned features raised, never above the machine maximum
- the print-time limit of the goal, re-checked on the written file

## `test/verify.py` (independent checker)
`python test/verify.py original.gcode optimized.gcode [--reordered] [--arc-tol 0.012]`
- its own position-tracking parser (relative E), exact `Decimal` E per layer
- multiset of extrusion moves including Z; arc chains with vertex, midpoint, direction and sweep checks
- without `--reordered`: line-by-line alignment that only allows removable hop/retract lines, arcs consuming G1 lines, `Z removed from travel`, changed F/S values and inserted `G1 F`/`M106`/`M204`

## `test/goal_matrix.py`
6 prints × 3 goals × 5 variants (full, no accel, no reorder, no hop skip, no reorder + arcs on) + 3 stress runs. Checks the goal rules, validity of every variant, the acceleration at every marker, and writes the per-feature time table (`test/results/goal_matrix.md`).

## Other tests
- 12-case regression (each print, default and `--goal speed --fix-strings --arcs on`) with `verify.py`
- `test/test_presets.py`: preset creation/migration/removal, `BambuStudio.conf` with MD5 trailer (synthetic fixture)
- `test/ui_shots.py`: all windows at 100/125/150/200% scaling, every button fully visible
- frozen exe `--self-test`, frozen exe run under Wine + `verify.py`, installer install/upgrade/uninstall smoke test under Wine
