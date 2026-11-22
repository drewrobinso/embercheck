# How each optimization works

Each page explains what the optimization changes, when it applies, what it never touches, how it is checked, and what it measured on the six reference prints (Bambu Studio 02.09.01.70, H2S 0.4, see the README's test results). EmberCheck works with every Bambu Lab printer and, since 1.5.0, with PrusaSlicer G-code for Marlin printers; machine limits come from each G-code's own printer profile.

| Page | What it does | On by default |
|---|---|---|
| [goals.md](goals.md) | Speed / Balanced / Quality: the promises and how the time limit is enforced | always |
| [thermal-speed-fan.md](thermal-speed-fan.md) | Thermal model, slowdowns and fan for hot layers, speed-ups for cool ones | yes |
| [overhangs-bridges.md](overhangs-bridges.md) | Unmarked overhangs slowed, overhang/bridge fan | yes |
| [acceleration.md](acceleration.md) | Speed-aware M204 per feature, and the 1.4.0 M204 line reduction | yes (`--no-accel`) |
| [travel-order.md](travel-order.md) | Smart island order inside infill features (nearest neighbour + 2-opt) | yes since 1.4.0 (`--no-reorder`) |
| [hop-retract-skip.md](hop-retract-skip.md) | Skip Z-hops (and on Speed, retractions) on short infill travels | Speed, Balanced (`--no-hop-skip`) |
| [arc-fitting.md](arc-fitting.md) | ArcWelder-style G2/G3 with exact E; Bambu firmware support | `auto`: off on curve-planning printers |
| [stringing.md](stringing.md) | Open-air travel analysis and optional added retractions | analysis yes, fix `--fix-strings` |
| [prusaslicer.md](prusaslicer.md) | PrusaSlicer / Marlin support (Creality Ender-3 V2 Neo): setup, presets, what differs from Bambu Studio, results, limits | when the G-code is from PrusaSlicer |
| [verify.md](verify.md) | The EmberCheck stamp, `--check-stamp`, runs.log, and what Bambu Studio prints/previews (with source references) | always |
| [safety-validation.md](safety-validation.md) | Built-in validator, `verify.py`, the goal matrix and UI tests | always |
