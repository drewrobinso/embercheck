# How to verify that Bambu Studio (or PrusaSlicer) prints the optimized file

Short version: **yes, it does.** Bambu Studio runs EmberCheck on the plate's temporary G-code, re-draws the preview from the file EmberCheck wrote, and builds the file it prints, sends or exports from that same file. EmberCheck stamps every file it writes so you can check this yourself.

## 1. Check the stamp

Every optimized G-code gets a comment block right after Bambu's header block:

```
; HEADER_BLOCK_END
; EMBERCHECK_BLOCK_START
; EmberCheck 1.4.2 - print optimizer for Bambu Studio (https://github.com/drewrobinso/embercheck)
; date: 2026-11-21 20:27 -0500
; goal: balanced (time limit: +2%)
; print time: 2h 45m -> 2h 29m (-16m, -9.8%) [Bambu Studio estimate, scaled by EmberCheck's motion model]
; by feature: acceleration -4m 01s, hop/retract skip -9m 04s, travel order -3s, speed/cooling/overhang feeds -3m 07s
; arcs: off (H2S does its own curve planning, Bambu Studio turns arc fitting off for it too)
; changes: 8285 feeds, 2 fan, 1187 M204 raised, 4959 Z-hops / 0 retracts skipped, 1965 overhang segments slowed, M73 progress and remaining time updated
; thermal model: hot layers 0 -> 0, cold layers 100 -> 88
; checked: same layers, same extrusion per layer (exact), start/end/AMS/timelapse G-code unchanged
; verify: EmberCheck.exe --check-stamp FILE.gcode|FILE.3mf  (docs/verify.md)
; body_sha256: a90e2c4eeb5d3c47a50cfe4d6ea863cb8e5c80ce13bafc57232b89e740fc862b
; EMBERCHECK_BLOCK_END
```

- `body_sha256` is the SHA-256 of the whole file **without** this block (UTF-8, line endings as written). If a single byte of the G-code changes after EmberCheck wrote it, the hash no longer matches.
- The block is plain ASCII `;` comments, each under 200 characters. Printers ignore comments; Bambu's header block, the thumbnails and the config block stay byte-identical, and they stay where they were.

**Where to find it**
- *Export G-code* (or *Export plate sliced file* → `.gcode.3mf`, then open `Metadata/plate_1.gcode` inside the zip): the block is near the top.
- **Check a file:** `"%LOCALAPPDATA%\Programs\EmberCheck\EmberCheck.exe" --check-stamp "C:\path\plate.gcode.3mf"` (or a `.gcode`). It prints *Stamp OK* and exits 0 if the G-code is exactly what EmberCheck wrote. For a `.3mf` it also checks Bambu's `Metadata/plate_N.gcode.md5`. From the installed exe it shows the result in a message box.
- **Receipt log:** every optimized file adds one tab-separated line to `%LOCALAPPDATA%\EmberCheck\runs.log`: time with UTC offset, file, goal, print time before → after, the source of the times, and `body_sha256`. Compare that hash with the stamp of a file you exported or printed.
- The full report (`Documents\EmberCheck\reports\`) shows the same hash.

## 2. What Bambu Studio does with the file (from its source)

Checked in the Bambu Studio source at tag `v02.09.01.70` (released 2026-11-03) and `v02.08.02.61`:

| Step | Source | What happens |
|---|---|---|
| Post-processing | `src/slic3r/GUI/BackgroundSlicingProcess.cpp`, `finalize_gcode()`, line 861 | `run_post_process_scripts(m_temp_output_path, false, "File", m_temp_output_path, ...)`: the scripts (EmberCheck) edit the plate's temporary G-code **in place**. |
| Preview | same file, lines 866–895 (status *"Updating preview with post-processed G-code"*, line 881 in 02.09.01.70, line 862 in 02.08.02.61) | Bambu re-parses the post-processed file and replaces only the toolpath (`moves`, `lines_ends`). The source comment says it keeps the slicer's `print_statistics`, filament maps and so on. **The preview shows EmberCheck's toolpath, but the time and filament estimate in the slice panel stay from the original slice.** |
| The plate's G-code file | `src/libslic3r/GCode.cpp`, `GCode::do_export()` line 2163 | `result->filename = path`: the G-code result points at that same temporary file. |
| Print / Send to a Bambu printer | `src/slic3r/GUI/Plater.cpp`, `send_gcode_legacy()` line 28492; `export_3mf(..., SaveStrategy::WithGcode ...)` line 28604 | The print job is a 3MF built with the plate's G-code. |
| G-code inside that 3MF | `src/slic3r/GUI/PartPlate.cpp`, `store_to_3mf_structure()` line 7504 | `plate_data_item->gcode_file = m_plate_list[i]->m_gcode_result->filename`: the post-processed temporary file. |
| `plate_N.gcode.md5` | `src/libslic3r/Format/bbs_3mf.cpp`, lines 7177–7200 | The MD5 is computed from that file when the 3MF is written, so it matches EmberCheck's output. |
| Export G-code | `BackgroundSlicingProcess.cpp`, `export_gcode()` lines 904–915 | Copies the post-processed temporary file to the path you chose. |
| Export plate sliced file | `Plater.cpp`, `export_gcode_3mf()` line 27039 | Same 3MF export with `WithGcode`. |
| Third-party print hosts | `BackgroundSlicingProcess.cpp`, lines 970–979 | When uploading to a non-Bambu print host, Bambu runs the scripts **again** on a copy. EmberCheck sees its own stamp and leaves that copy unchanged (it never optimizes a file twice). |

**So:** Print, Send, Export G-code and Export plate sliced file all carry the post-processed (EmberCheck) G-code, and the preview shows it. Only Bambu Studio's own time/filament numbers in the slice panel are from before EmberCheck.

## 2b. PrusaSlicer (1.5.0)

Checked in the PrusaSlicer source (`src/slic3r/GUI/BackgroundSlicingProcess.cpp`, `finalize_gcode()` and `prepare_upload()`, tag `version_2.9.2`; same flow in the 2.9.7 build used for the tests):
- PrusaSlicer slices into a temporary G-code. Post-processing runs only when you **export or upload**: `finalize_gcode()` calls `run_post_process_scripts()` on a copy of the temporary file, then copies that post-processed copy to the export path (file or SD card). *Send to printer* (`prepare_upload()`) does the same on its own copy before the upload.
- So the exported / uploaded file is the optimized one, but PrusaSlicer's **preview, sidebar time and `{print_time}` in the file name are from before EmberCheck**.
- The stamp is inserted right after PrusaSlicer's first line (`; generated by PrusaSlicer …`). Example from the Ender-3 V2 Neo sample (Balanced):

```
; generated by PrusaSlicer 2.9.7 on 2026-11-22 at 03:25:11 UTC
; EMBERCHECK_BLOCK_START
; EmberCheck 1.5.0 - print optimizer for PrusaSlicer (https://github.com/drewrobinso/embercheck)
; goal: balanced (time limit: +2%)
; print time: 12h 00m -> 10h 48m (-1h 12m, -10.1%) [PrusaSlicer estimate, scaled by EmberCheck's motion model]
; changes: 11321 feeds, 0 fan, 0 M204 raised, 0 Z-hops / 0 retracts skipped, 368 overhang segments slowed, no M73 progress lines in the file
; checked: same layers, same extrusion per layer (exact), start/end/custom G-code and PrusaSlicer footer unchanged
; body_sha256: ...
; EMBERCHECK_BLOCK_END
```
(some lines left out). `--check-stamp` works on PrusaSlicer files the same way.
- When the profile writes `M73` lines (PrusaSlicer's *Supports remaining times*), their `P`/`R` values are rewritten; `Q`/`S` (silent mode) are left as sliced. Creality's profiles turn remaining times off, so the Ender's display shows its own estimate.

## 3. Print time on the printer

- EmberCheck rewrites the `M73 P<percent> R<minutes>` lines in the printed part of the G-code for the new motion, so the printer's progress bar and remaining time follow the optimized print once layer 1 starts. The few `M73` lines inside Bambu's start G-code are left exactly as sliced (EmberCheck never changes the start G-code), so during the start sequence the printer still shows Bambu's original remaining time.
- Not verified: whether Bambu Handy or the printer's file list shows the time stored in the 3MF's `slice_info` metadata (that is written from Bambu's original estimate).

## 4. Independent check (developers)

`python test/verify.py original.gcode optimized.gcode [--reordered] --arc-tol 0.012` removes the EmberCheck block, checks `body_sha256` on its own (without EmberCheck's code), then compares the two files: same layers, same extrusion per layer (exact decimals), start/end/AMS/temperature lines identical. See [safety-validation.md](safety-validation.md).
