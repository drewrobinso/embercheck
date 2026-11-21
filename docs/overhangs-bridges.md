# Overhangs and bridges

## What it does
- Each outer/inner wall segment is compared with the layer below (shapely buffer of the previous layer's extrusions).
- Overhangs over 50% that Bambu Studio did not already mark get the profile's own overhang speed for that degree (`overhang_3_4_speed`, `overhang_4_4_speed`), plus an overhang-fan boost on PLA/PETG/TPU.
- Quality also slows 25–50% overhangs; on Speed/Balanced they are report-only.
- Bridges printed below the overhang fan speed get their fan raised.
- On Speed/Balanced, overhang slowdowns are part of the time budget: if they don't fit, the lowest-value ones are dropped (reported as `budget_dropped_overhangs`).

## Never touched
Overhangs and bridges the slicer already handles, E values, temperatures.

## Results (1.4.0)
Overhang segments slowed: towers 16 (Speed/Balanced) and 26 (Quality); speakers 1,965 (Speed/Balanced) and 2,187 (Quality).

`--no-overhang` and `--no-bridge-fan` turn these off.
