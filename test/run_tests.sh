#!/bin/bash
# End-to-end tests on Bambu Studio 02.09.01.70 CLI-sliced H2S G-code
cd /workspace/print-optimizer
R=test/results; rm -rf $R; mkdir -p $R
for c in tower_petg tower_pla tower_asa tower_abs speaker_petg speaker_asa; do
  cp test/out/$c/plate_1.gcode "$R/$c.gcode"
  python3 src/embercheck.py "$R/$c.gcode" -o "$R/$c.opt.gcode" --report "$R/$c.report.html" --reorder --fix-strings 2>&1 | grep -E "result|FAILED"
done
# PrusaSlicer / Ender-3 V2 Neo (1.5.0): goal rules + verify.py on the fixtures (and the sample if present), preset logic
python3 test/prusa_matrix.py | tail -2
python3 test/test_prusa_presets.py | tail -1
