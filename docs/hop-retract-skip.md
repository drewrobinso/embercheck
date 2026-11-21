# Z-hop / retraction skip on short infill travels

New in 1.4.0.

## Why
Bambu's H2S profile retracts and lifts before almost every infill travel (`z_hop` 0.4 mm "Auto Lift", `retraction_minimum_travel` 1 mm, wipe on). A typical group is:

```
G1 X.. Y.. E-.38        ; wipe while retracting (inside ; WIPE_START / ; WIPE_END)
G1 E-.02 F1800          ; rest of the retraction
G17
G3 Z.6 I.. J.. P1 F60000 ; spiral Z lift
G1 X.. Y.. Z.6          ; travel
G1 Z.2                  ; lower
G1 E.4 F1800            ; un-retract
```

On the PETG speaker there are ~8,100 of these in sparse infill, most for travels of a few millimetres across infill that is already printed.

## What it does
For a group between two extrusions of the **same** infill feature (sparse or internal solid infill), on layer 3 and up:
- exactly one travel, nothing protected, nothing we inserted, only motion / `G17` / `M204` / `M73` lines
- the travel is ≤ 10 mm (Speed) or ≤ 5 mm (Balanced), and its straight path stays over the layer's printed area (less than 0.05 mm outside the union of the layer's extrusions)
- the lift goes up from the layer height, the travel runs at exactly the lifted height, the lower returns to the layer height, and the next extrusion is at the layer height

Then:
- **Balanced (`hop`)**: the spiral lift and the lower are removed and the travel's Z word is stripped, so it travels at layer height. Wipe, retract and un-retract stay.
- **Speed (`hop+retract`)**: the wipe, retract and un-retract are removed too, but only when their E adds up to exactly 0 (checked to 1e-6 in decimal), so the net E of the group is unchanged. The travel then starts where the extrusion ended.
- **Quality**: off.

The time saved is the modelled duration of the removed lines (plus the changed travel), and it counts as credit for the time limit.

## Risks and why it is limited this way
- Removing a hop can make the nozzle drag over curled or blobbed infill. That is why it is limited to short travels over printed **infill** of the same feature, never walls, tops, open air or the first layers.
- Removing a retraction can cause oozing/stringing on long travels. On Speed it is limited to ≤ 10 mm over printed infill, where any string is hidden inside the part.
- **Not yet confirmed by a real print.** If you see scars on top of infill or stringing inside the part, use `--no-hop-skip` or AI Balanced/Quality.

## Checks
- Built-in validator: exact per-layer E, same extrusion moves, protected blocks unchanged.
- `verify.py` without `--reordered` aligns every line and only allows removed Z lift/lower, spiral lifts, E-only retracts and wipe moves, and `Z removed from travel`. Tamper test: changing one un-retract's E makes it FAIL.

## Results (1.4.0)
| Print | Speed: hops / retracts skipped, time | Balanced: hops skipped, time |
|---|---|---|
| speaker PETG | 6,855 / 6,787, −10.05% | 4,959, −5.49% |
| speaker ASA | 1,724 / 1,708, −2.56% | 926, −1.08% |
| tower PLA | 52 / 52, −0.36% | 14, −0.07% |
| tower PETG | 10 / 10, −0.05% | 5, −0.02% |
| tower ABS / ASA | 0 | 0 |
