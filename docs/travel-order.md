# Smart travel order

Opt-in (`--reorder`) since 1.0; on by default for every goal since 1.4.0, now with the time saving modelled and credited to the budget.

## What it does
- Works per layer, inside barrier-free runs of one re-orderable feature: sparse infill, internal solid infill, gap infill, support. Walls, top/bottom surfaces, bridges and anything next to a protected block are never moved.
- Splits a run into units that each start with a travel and contain whole extrusions, retract to retract. The first unit stays first and the last unit stays last, so whatever follows sees the same nozzle position.
- Orders the movable units by **nearest neighbour**, keeps the slicer's order if that is shorter, then improves it with **2-opt** (runs of up to 80 units, up to 20 passes).
- A unit's own moves are never reversed or changed, so the E values, widths and directions stay the same; only the order of whole units changes.
- A new order is used only if it saves more than 1 mm and more than 2% of that run's travel.
- Time saved = the travel time of the original order minus the new order, using each travel's own feed and acceleration (`seg_time`). It counts as credit for the Speed/Balanced time limit.
- After re-ordering, `M204`, `G1 F` and `; LINE_WIDTH` are re-emitted where a unit needs a different value than the one before it.

## Checks
- Built-in validator: same per-layer E (exact), same multiset of extrusion moves.
- `verify.py --reordered`: same checks, independent parser. (The strict line-by-line alignment only applies to files without re-ordering; `goal_matrix.py` runs it on the `no_reorder` variants.)

## Results (1.4.0)
- PETG speaker: 77 runs re-ordered, 2,046 mm less travel (~3 s).
- Time effect on the six reference prints: between −0.03% and +0.03%. Bambu's own order is already close to optimal on these prints; prints with many separate infill islands per layer gain more.

`--no-reorder` keeps the slicer's order.
