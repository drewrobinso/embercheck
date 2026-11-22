# PrusaSlicer and Marlin printers (Creality Ender 3 V2 Neo)

New in 1.5.0. EmberCheck also optimizes G-code from **PrusaSlicer** (tested with 2.9.7) for printers with **Marlin 2, Marlin (legacy) or Klipper** G-code flavour. It was built and tested on a real PrusaSlicer 2.9.7 slice for the **Creality Ender-3 V2 Neo** (`0.20 mm NORMAL (0.4 mm nozzle) @CREALITY`, `Generic PLA @CREALITY`). The Bambu Studio path is unchanged: on the six Bambu reference prints the 1.5.0 output is byte-identical to 1.4.2 (stamp excluded).

## Setup

**With the installer (Windows):**
1. Open PrusaSlicer once, pick your printer and the print profile you normally use (for the Ender: *0.20 mm NORMAL (0.4 mm nozzle) @CREALITY*), then close PrusaSlicer.
2. Run `EmberCheck-Setup-1.5.0.exe`. When PrusaSlicer is found (`%APPDATA%\PrusaSlicer`), the options page shows **Add EmberCheck print presets to PrusaSlicer** (on by default). The Bambu Studio option only appears if Bambu Studio is installed (or if PrusaSlicer is not).
3. Start PrusaSlicer. In the **Print settings** drop-down, under *User presets*, there are three new presets:
   - `0.20 mm NORMAL (0.4 mm nozzle) @CREALITY - EmberCheck Balanced`
   - `0.20 mm NORMAL (0.4 mm nozzle) @CREALITY - EmberCheck Speed`
   - `0.20 mm NORMAL (0.4 mm nozzle) @CREALITY - EmberCheck Quality`
4. Pick one, slice, and **Export G-code** (or *Send to printer* / *Export to SD card*). PrusaSlicer runs EmberCheck on the exported file: a progress window appears, then the results card. The file on disk / SD card is the optimized one.

The presets are full copies of the print profile you had selected (every setting, so they behave exactly like it) with one difference: *Print Settings → Output options → Post-processing scripts* has an extra line,
```
"C:\Users\<you>\AppData\Local\Programs\EmberCheck\EmberCheck.exe" --goal balanced
```
Any post-processing script the profile already had is kept before it. Each preset still shows its parent (`inherits`), so PrusaSlicer lists it under the same printer and shows the differences from the system profile.

**Other layer heights or printers:** the presets are made for the print profile that is selected in PrusaSlicer (`PrusaSlicer.ini`). Select another one in PrusaSlicer, close it, and run Start menu → EmberCheck → **Add PrusaSlicer presets**. Presets made earlier are kept and updated. A user preset of your own can be the base too: its settings are copied and its own post-processing scripts are kept. Silent install: `/PRUSABASE="0.20 mm NORMAL (0.4 mm nozzle) @CREALITY;0.16 mm OPTIMAL (0.4 mm nozzle) @CREALITY"`.

**By hand (or the Python version):** add the line above to *Post-processing scripts* of any print preset (Expert mode). PrusaSlicer appends the G-code path as the last argument and sets `SLIC3R_PP_OUTPUT_NAME`; EmberCheck edits the file in place and the card shows the real file name.

**Rules for the presets** (`src/prusa_presets.py`):
- A preset with the same name that EmberCheck did not create is never overwritten.
- If you edit an EmberCheck preset in PrusaSlicer and save it, a later install only updates its post-processing line (new exe path); your changes stay.
- Uninstall deletes only the presets EmberCheck created (listed in `prusa_presets_manifest.json` and still marked *Created by EmberCheck* in their notes). Presets you changed are copied to `%LOCALAPPDATA%\Programs\EmberCheck\preset_backups\prusaslicer\` first. Your own presets, the vendor profiles and `PrusaSlicer.ini` are never touched.
- Restart PrusaSlicer after installing or uninstalling: it reads presets only at start-up.

## What is different from Bambu Studio

| | Bambu Studio | PrusaSlicer |
|---|---|---|
| When it runs | after slicing | on **export** (Export G-code, Send to printer, Export to SD). The preview in PrusaSlicer shows the toolpath **before** EmberCheck. |
| Markers read | `; FEATURE:`, `; CHANGE_LAYER`, `; LINE_WIDTH:` | `;TYPE:`, `;LAYER_CHANGE`, `;Z:`, `;HEIGHT:`, `;WIDTH:`, `;WIPE_START/END` |
| Settings read | header config block | `; prusaslicer_config = begin … end` at the end of the file (machine limits, speeds, fan, cooling, retraction, filament flow limit) |
| Time "before" | `; model printing time:` | `; estimated printing time (normal mode)` from the footer |
| Acceleration line | `M204 S` | `M204 P` for Marlin 2 (print moves), `M204 S` for Marlin legacy / Klipper |
| Results card button | *Continue to Print* | *Close* (PrusaSlicer has already finished exporting) |
| Protected | AMS, timelapse, M622/M623 | start/end G-code, every `;TYPE:Custom` block (layer-change, colour-change, tool-change G-code), `M600`, `M601`, `M0/M1`, `M25`, `M486`, `M117/M118`, `M240`, `M701/M702`, `T<n>` |

PrusaSlicer's feature types are mapped onto EmberCheck's: *External perimeter* = outer wall (never sped up), *Perimeter* = inner wall, *Internal infill* = sparse infill, *Solid infill* = internal solid infill, *Top solid infill* = top surface (never sped up), *Bridge infill* = bridge, *Overhang perimeter* = overhang wall, *Skirt/Brim*, *Support material*, *Gap fill*, *Ironing*.

**Not supported (the file is left unchanged and the card says why):** binary G-code (`.bgcode`, *Supports binary G-code* in the printer settings), absolute E (M82), firmware retraction (G10/G11), spiral vase, RepRap/Sprinter/Smoothie/other flavours. Other slicers (Cura, SuperSlicer, OrcaSlicer, …) are not supported.

## Ender 3 V2 Neo: what the sample showed

The real slice (PrusaSlicer 2.9.7, 500 layers at 0.2 mm, 100 mm tall, PLA 205 °C, PrusaSlicer estimate **11h 59m 55s**):
- **Acceleration is already at the machine limit.** Creality's profile sets `M201 X500 Y500` and prints at `M204 P500`, so EmberCheck cannot raise acceleration on this printer (0 M204 lines changed). The savings come from feeds.
- **Part fan is 100% all the time** (fan always on, min = max = 100%), so there is no fan headroom; the PLA is never too hot (0 hot layers). Fan values are unchanged.
- **The profile prints slowly** (infill 50 mm/s, perimeters 40, external perimeters 25) while the filament flow limit is 15 mm³/s, so inner walls and infill have room: Balanced runs them up to 1.25×, Speed up to 1.5×, still under 15 mm³/s.
- **Bowden retraction:** 5 mm at 60 mm/s with a 70% wipe, no Z-hop. On Speed, retract+wipe pairs on short in-infill travels over printed area are skipped (net E exactly 0): 1,091 on the sample, about 2 minutes.
- No `M73` lines (Creality's profile turns *remaining times* off), so there is nothing to update for the printer display; the stamp says so.
- Arc fitting is off in the profile, so EmberCheck leaves it off (`--arcs on` forces it).

Results (EmberCheck 1.5.0 motion model, scaled to PrusaSlicer's estimate; `test/prusa_matrix.py`):

| Goal | Before | After | Change | Checks |
|---|---|---|---|---|
| Speed | 11h 59m 55s | 9h 56m 24s | −2h 03m 31s (−17.2%) | validator OK, `verify.py` PASS (also strict line alignment without travel re-order) |
| Balanced | 11h 59m 55s | 10h 47m 30s | −1h 12m 25s (−10.1%) | same |
| Quality | 11h 59m 55s | 12h 03m 46s | +3m 51s (+0.5%), 5,321 overhang segments slowed | same |

Extrusion is identical (total E 39,900.09797 mm before and after on every goal). **These are model numbers; nothing has been printed yet.** Print a small test part with the Speed preset first: 1.5× inner walls and infill on a Bowden extruder may need a little more temperature for some PLAs.

## Known limits
- PrusaSlicer's own time in the sidebar and `{print_time}` in the file name stay from the original slice (PrusaSlicer computes them before post-processing). The card, report and stamp show before → after.
- `M73 Q/S` (silent-mode) values are not rewritten; `M73 P/R` are.
- With Marlin 2, `M204 P` does not change travel acceleration (`M204 T`); the estimate assumes travel acceleration equal to the print value when it raises acceleration. This does not apply to the Ender (no raise is possible at 500 mm/s²).
- *Solid infill* includes bottom surfaces over supports; it is sped up like internal solid infill (never the first 2 layers).
- Thermal model numbers are uncalibrated, as for Bambu (see the README).
