# Travel and stringing analysis

## What it does
- For every travel, measures how much of its straight path is outside the layer's printed area (open air).
- Reports how many open-air travels exist and how many of them are not retracted first.
- `--fix-strings` (off by default) adds a net-zero retract / un-retract pair (using the profile's retraction length and speed) before un-retracted travels with at least 2 mm in open air.
- The report recommends Bambu Studio's *Avoid crossing wall* (`reduce_crossing_wall`), which re-routes travels properly; this tool can't re-route.

## Checks
The inserted pairs add exactly 0 E per layer; validator and `verify.py` check this.

## Results
2–12 retractions were added on the reference prints with `--fix-strings`.
