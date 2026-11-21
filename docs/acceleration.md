# Speed-aware acceleration (M204)

Added in 1.3.0; the M204 line reduction is new in 1.4.0.

## What it does
- Per Bambu `;FEATURE:` type, on layers 3 and up that are not hot:
  - Speed: sparse infill, internal solid infill and inner walls up to `machine_max_acceleration_extruding` (header value).
  - Balanced: the same features, ×1.5 of the slicer's value, capped at the machine maximum.
  - Quality: sparse and internal solid infill only, ×1.2.
- Travels and wipes between two raised extrusions of the same feature and the same original value keep the raised value, so M204 doesn't toggle around every hop.
- Never raised: outer walls, overhangs, bridges, top surfaces, the first 3 layers, hot layers (it would shorten their cooling), anything inside AMS / tool-change / timelapse blocks, and moves the slicer gave a different value (for example 250 mm/s² short travels).
- The motion model includes the new acceleration, so M73 is right, and the saving is shown separately.

## Restoring the slicer's value
The slicer's own value is written back before:
- every `; FEATURE:` and `; CHANGE_LAYER` marker
- every protected line (AMS, tool change, timelapse, firmware conditional blocks)
- any move that was not planned with the raised value (a wipe block is checked as a whole: if any of its moves isn't planned, the restore goes before `; WIPE_START`)

1.3.0 also restored before every non-optimisable line, including comments, `G17` and `M73`, which wrote a restore + raise pair around almost every wipe. 1.4.0 skips those harmless lines and the slicer's own M204 lines:

| Print (Speed) | Original | 1.3.0 | 1.4.0 |
|---|---|---|---|
| speaker PETG | 2,105 | 20,179 | 3,871 |
| speaker ASA | 2,105 | 9,347 | 3,857 |
| tower PLA | 1,391 | 2,842 | 2,636 |
| tower PETG | 1,391 | 3,227 | 2,679 |

The time saved by acceleration is identical to 1.3.0 (for example −4.00% on the PETG speaker, Speed), and every output keeps the slicer's value at every marker.

## Checks
- The built-in validator rejects the output if any extrusion move outside the planned features has a different acceleration, or if a value exceeds the machine maximum.
- `goal_matrix.py` compares the acceleration in effect at every feature change, layer change and AMS block (M620/M621) with the original's.

## Results (1.4.0, time saved)
Speed: towers 0.27–2.21%, speakers 3.86–4.19%. Balanced: 0.31–1.35% / 2.43–2.47%. Quality: 0.21–0.51% / 1.10–1.14%.

`--no-accel` turns it off.
