# Arc fitting (G2/G3)

New in 1.4.0.

## Bambu firmware support
- Bambu printers' firmware accepts G2/G3, and Bambu Studio's own *Arc fitting* option (ArcWelder-based, `enable_arc_fitting`) writes them ([Bambu Lab wiki: Arc move](https://wiki.bambulab.com/en/software/bambu-studio/acr-move)).
- The H2D, H2D Pro, H2S, H2C, X2D, H3C, P2S and A2L firmware has its own **curve planning**, and Bambu Studio's system profiles turn arc fitting off for these printers (`enable_arc_fitting = 0` in the resolved 02.09.01.70 profiles; X1C, A1 mini and the other older models have it on). The H2S test slices have `enable_arc_fitting = 0`.
- Since 1.4.2, `--arcs auto` (the default) follows the **target printer profile's own `enable_arc_fitting`** from the G-code's config block, and is always off for the curve-planning models above (detected from `printer_model`). On an X1C-profile copy of the speaker slice it fitted 621 arcs replacing 2,787 moves (verify.py PASS). `--arcs on` forces it, `--arcs off` disables it. The card and report say when and why it is off.

## What it does
- Looks at runs of 3 or more consecutive `G1 X Y E` moves in the emitted file that come from consecutive original lines of the same feature, with no comments and `F` only on the first move.
- Grows each arc greedily while one circle fits:
  - circle through the first, middle and last point; radius 0.5–300 mm
  - the centre is rounded to 3 decimals (as `I`/`J` will be written) **before** the checks, so the written arc, not an ideal one, is checked
  - every vertex and every segment midpoint within the tolerance of the circle, and every chord's bow too
  - turns one way only, sweep < 330°, extrusion per mm within ±3% along the arc, arc length within 1% of the polyline
- Tolerance: `--arc-tol`, else the profile's `resolution` clamped to 0.005–0.05 mm (0.01 mm on the test profile).
- Writes `G2`/`G3 X Y I J E [F]`, where E is the **exact decimal sum** of the replaced E values (no float rounding).

## Checks
- Built-in validator and `verify.py` expand every arc back into the remaining original segments: start/end, every vertex and midpoint within the tolerance, the same turning direction, and the drawn sweep equal to the sum of the segments' sweeps. The E sum must match exactly.
- Tamper tests: changing an arc's E by 0.00001 or flipping G2 ↔ G3 makes `verify.py` FAIL.
- Bug found and fixed during 1.4.0 testing: small arcs (r ≈ 0.65 mm) passed the fitter's check with the exact centre but failed the validator after I/J rounding. The validator refused the file (the G-code was left unchanged); the fitter now checks the rounded centre.

## Results (1.4.0, `--arcs on` forced on the H2S slices)
- Speakers: 621–622 arcs replace 2,787–2,790 segments; towers: none (straight lines).
- Model time: −0.01% to 0.00%. An arc has the same length as its segments, so our model shows no saving; the benefit on printers without curve planning is fewer, smoother commands (less stutter on dense curves). We don't claim a time gain.
