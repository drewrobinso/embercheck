# Goals: Speed, Balanced, Quality

Every `EmberCheck <Goal>` preset runs the optimizer with `--goal speed|balanced|quality`. Since 1.3.0 each goal makes a promise that is enforced and tested, not just a different set of factors.

| Goal | Promise | Tools |
|---|---|---|
| Speed | Model print time ≤ the original | speed-ups up to 1.5×, acceleration up to the machine maximum, smart travel order, skip Z-hop + retract on infill travels ≤ 10 mm |
| Balanced (default) | Fixes most hot layers, time ≤ +2% | speed-ups up to 1.25×, acceleration ×1.5, smart travel order, skip Z-hop only on infill travels ≤ 5 mm |
| Quality | Quality first, may add time | no feed speed-ups, 5 °C bigger safety margin, 25–50% overhangs slowed too, acceleration ×1.2 on infill only, smart travel order, all hops/retractions kept |

Arc fitting (`--arcs auto|on|off`) is the same for all goals.

## How the time limit is enforced

1. The optimizer plans speed-ups, acceleration, hot-layer fixes (fan first when it costs no time, then slowdowns) and overhang slowdowns.
2. The time saved by smart travel order and hop/retract skip is computed and counted as credit.
3. `enforce_budget` drops the lowest-value slowdowns (time cost against heat or overhang benefit) until the plan fits `time ≤ original × (1 + limit) + credit`.
4. The G-code is written, and the time is estimated again on the written file with the same estimator that sets M73. If it is still over the limit, more slowdowns are dropped and the file is written again.
5. Hot layers that were left unfixed to keep the limit are listed in the first recommendation (*Goal*), suggesting EmberCheck Balanced / EmberCheck Quality or slicer cooling settings.

`--no-time-limit` turns the limit off (pre-1.3 behaviour).

## Rules checked by `test/goal_matrix.py`

For each of the six prints:
- valid: built-in validator and `verify.py` pass for every goal and every variant (full, no accel, no reorder, no hop skip, no reorder + arcs forced on)
- `speed ≤ 0%`, `balanced ≤ +2%` (also for every variant)
- Balanced fixes at least half of the hot layers Quality can fix, unless the time limit binds
- Quality hot layers ≤ Balanced, Quality overhang slowdowns ≥ Balanced
- `t(Speed) ≤ t(Balanced) ≤ t(Quality)`
- stress cases (speed-ups and acceleration off, only slowdowns available) still keep their limits

1.4.0: all rules pass (see the README's test results).
