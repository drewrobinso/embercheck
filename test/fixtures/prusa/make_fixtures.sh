#!/bin/bash
# Re-create the PrusaSlicer test fixtures (test/fixtures/prusa/ender3v2neo_tower_*.gcode.gz):
# test/tower.stl sliced by PrusaSlicer 2.9.7 (the Windows zip from github.com/prusa3d/PrusaSlicer/releases, run with
# Wine) with the stock "Creality Ender-3 V2 Neo (0.4 mm nozzle)" / "0.20 mm NORMAL (0.4 mm nozzle) @CREALITY" /
# "Generic PLA @CREALITY" profiles, plus one change per fixture.
# usage: make_fixtures.sh <prusa-slicer-console.exe> <config.ini>
#   config.ini = the full configuration of a G-code sliced with those profiles, e.g.
#   sed -n '/^; prusaslicer_config = begin/,/^; prusaslicer_config = end/{s/^; //p}' sliced.gcode | sed '1d;$d' > config.ini
set -e
PS="$1"; CFG="$2"; HERE="$(cd "$(dirname "$0")" && pwd)"; STL="$HERE/../../tower.stl"; T="$(mktemp -d)"
export WINEDEBUG=-all
mk() { name=$1; shift; cp "$CFG" "$T/$name.ini"
  for kv in "$@"; do k="${kv%%=*}"; v="${kv#*=}"
    if grep -q "^$k = " "$T/$name.ini"; then sed -i "s|^$k = .*|$k = $v|" "$T/$name.ini"; else echo "$k = $v" >> "$T/$name.ini"; fi; done
  wine "$PS" --export-gcode --load "$T/$name.ini" --output "$T/$name.gcode" "$STL" >/dev/null 2>&1
  gzip -9 -c "$T/$name.gcode" > "$HERE/ender3v2neo_tower_$name.gcode.gz"; echo "ender3v2neo_tower_$name.gcode.gz"; }
mk pla                                                                     # stock profile (no M73, no Z-hop, Marlin 2)
mk m73hop "remaining_times=1" "retract_lift=0.4" "retract_lift_above=0"    # M73 progress lines + 0.4 mm Z-hop
mk petg "filament_type=PETG" "temperature=240" "first_layer_temperature=240" "remaining_times=1" "slowdown_below_layer_time=5"
mk arcs "arc_fitting=emit_center"                                          # G2/G3 arcs from the slicer
mk legacy "gcode_flavor=marlin" "remaining_times=1"                        # Marlin (legacy) flavour: M204 S
rm -rf "$T"
