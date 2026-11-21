#!/bin/bash
# usage: slice.sh model.stl material outname
T=/workspace/print-optimizer/tools; O=/workspace/print-optimizer/test/out/$3; mkdir -p $O
$T/squashfs-root/AppRun --slice 0 --curr-bed-type "Textured PEI Plate" --arrange 1 --orient 0 --load-settings "$T/flat/machine.json;$T/squashfs-root/resources/profiles/BBL/process/0.20mm Standard @BBL H2S.json" --load-filaments "$T/flat/$2.json" --outputdir $O --export-3mf $3.gcode.3mf "$1" > $O/log.txt 2>&1
rg -n "filament_type =|total filament weight|total layer|model printing time" $O/plate_1.gcode | head
