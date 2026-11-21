# Changelog

All notable changes. Versions follow `VERSION` in `src/bambu_optimizer.py`. Test numbers are from the build box (Bambu Studio 02.09.01.70 CLI slices for the H2S 0.4, six reference prints: four 225-layer towers in PLA/PETG/ABS/ASA and the 166-layer speaker adapter in PETG/ASA). Times are the optimizer's own motion model, not measured prints. Windows builds were tested under Wine 10, not yet on a real Windows PC.

## [1.4.0] - 2026-11-21

### Added
- **Smart travel order on by default** for every goal (was opt-in `--reorder`). Infill islands inside one feature are re-ordered by nearest neighbour + 2-opt; units are moved whole, never reversed. The travel time saved is now modelled and counted as credit for the goal's time limit. New `--no-reorder`. See [docs/travel-order.md](docs/travel-order.md).
- **Z-hop / retraction skip** on short infill travels (sparse or internal solid infill, layer 3+, same feature on both sides, straight path over the layer's printed area): Speed drops the spiral Z lift + lower and also the wipe + retract/un-retract pair when its E adds up to exactly 0, for travels ≤ 10 mm; Balanced drops only the Z lift/lower, for travels ≤ 5 mm; Quality keeps everything. New `--no-hop-skip`. *Why:* Bambu's H2S profile lifts and retracts before nearly every infill travel; on the PETG speaker that is ~8,100 groups. See [docs/hop-retract-skip.md](docs/hop-retract-skip.md).
- **Arc fitting** (ArcWelder-style G2/G3) with the exact decimal E sum of the replaced moves, checked against the rounded I/J centre. New `--arcs auto|on|off`; `auto` is off on printers with Bambu's curve planning (H2D, H2S, H2C, X2D, H2D Pro, A2L), where Bambu Studio also turns arc fitting off, and on for other printers. See [docs/arc-fitting.md](docs/arc-fitting.md).
- **Per-feature metrics** on the results card (travel order, hops/retracts skipped, arcs or why arcs are off) and in the report (time saved by acceleration, travel order and hop/retract skip, arcs, G-code size, M204 line count).
- **Buy Me a Coffee support**: `.github/FUNDING.yml` (`buy_me_a_coffee: drewrobinso`), a README badge and *Support development* section, and a small *Support this project* link at the bottom left of the results card that opens https://buymeacoffee.com/drewrobinso in the browser only when clicked. The link is defined once in `src/project_info.py`.
- Documentation: `CHANGELOG.md`, `docs/` with one page per optimization, README sections on the goals, features, flags, Windows SmartScreen / Smart App Control and signing, and the 1.4.0 results.

### Changed
- **Far fewer M204 lines.** The slicer's acceleration is still restored at every feature change, layer change, protected block and before any move we didn't plan, but no longer before comments, `G17`, `M73` or the slicer's own M204 lines, and a wipe block keeps the raised value when all of its moves are planned. M204 lines on Speed: PETG speaker 20,179 (1.3.0) → 3,871 (original 2,105); ASA speaker 9,347 → 3,857; PLA tower 2,842 → 2,636. No time result changed, and the acceleration at every marker is still the slicer's own.
- The time limit's re-check on the written file keeps the travel/hop credit.
- `verify.py` rewritten: own position-tracking parser, exact `Decimal` E per layer, extrusion multiset with Z, arc expansion with vertex/midpoint/direction/sweep checks (`--arc-tol`), and line-by-line alignment (without `--reordered`) that only allows removable hop/retract lines, arcs and changed F/S/M204 values.
- `test/goal_matrix.py` runs 5 variants per print and goal (full, no accel, no reorder, no hop skip, no reorder + arcs on) and writes the per-feature time table.
- The *Nothing else touched* line in the report now says that per-layer extrusion is exactly the same (instead of "no E values"), since retract pairs and arcs are merged with the exact E sum.

### Fixed (found during 1.4.0 testing, never released)
- Small arcs (r ≈ 0.65 mm) passed the fitter with the exact circle centre but were up to 0.0129 mm off after I/J rounding; the validator correctly refused the file. The fitter now checks the rounded centre with a 0.001 mm margin and also checks segment midpoints.
- A first version of the M204 reduction inserted restores inside wipe blocks after timelapse blocks; the validator refused those files (protected-block check). Fixed by treating `M73` as harmless and checking whole wipe blocks.

### Tests
- `goal_matrix.py`: 90 runs + 3 stress runs, **all rules PASS**, for the full runs and every variant. Speed: tower PLA −3.38%, PETG −7.36%, ABS −5.63%, ASA −4.67%, speaker PETG **−16.30%** (1.3.0: −6.21%), speaker ASA **−6.76%** (1.3.0: −4.19%). Balanced: −0.91% to −9.84%. Quality: −0.69% to +3.51%.
- Time saved by each feature (Speed): acceleration 0.27–4.19%; travel order −0.03% to +0.03%; hop/retract skip 0–10.05% (PETG speaker: 6,855 hops and 6,787 retracts skipped); arcs (forced on) 0.00% with 621 arcs replacing 2,787 segments on the speaker.
- 12-case regression (default and `--goal speed --fix-strings --arcs on`): all PASS with the built-in validator and `verify.py`.
- Tamper tests: arc E +0.00001, arc direction flip, one un-retract E changed: all FAIL as expected.
- `test_presets.py` OK; `ui_shots.py` 16/16 windows OK at 100/125/150/200%; `actionlint` OK.

## [1.3.0] - 2026-11-21

### Added
- **Goals with enforced promises.** Speed: model print time never above the original. Balanced: fixes most hot layers within +2%. Quality: quality first, may add time; no more hot layers than Balanced, at least as many overhang slowdowns. Ordering t(Speed) ≤ t(Balanced) ≤ t(Quality). Speed and Balanced fix hot layers with fan first (free), then drop the lowest-value slowdowns to keep the limit, re-checked on the written file; unfixed hot layers become the first recommendation. `--no-time-limit` restores the old behaviour. *Why:* in 1.2.1 Speed could end up slower than the original (speaker ASA +0.03%).
- **Speed-aware acceleration** (M204) per feature: sparse/internal solid infill and inner walls up to the machine maximum (Speed), ×1.5 (Balanced), infill-only ×1.2 (Quality). Never on outer walls, overhangs, bridges, top surfaces, the first 3 layers, hot layers or protected blocks; the slicer's value is restored at every feature/layer change and protected block, modelled for M73, and validated. Shown separately on the card and report. `--no-accel`.
- `test/goal_matrix.py` (rules on all six prints) and `test/ui_shots.py` (windows at 100/125/150/200%).

### Fixed
- **Buttons cut off on the results card at Windows display scaling** (reported as "Buttons are cut off, can't see which option i'm clicking!"). The windows are now DPI-aware (`SetProcessDpiAwareness`), Tk scaling follows the monitor DPI, buttons size to their text, the bottom row is packed first, the recommendations scroll, and the window is capped to the screen. This was planned as 1.2.2 and shipped in 1.3.0 instead.

### Tests
- Goal matrix: all rules PASS. Speed: tower PLA −3.02% (1.2.1: −0.81%), speaker ASA −4.19% (1.2.1: +0.03%), speaker PETG −6.21%. Balanced ≤ +2% on all prints. Stress cases (only slowdowns available): Speed +0.00%, Balanced +1.78%.
- `ui_shots.py`: 16/16 windows OK. 12-case regression with `verify.py`: PASS.
- Installer `PrintOptimizer-Setup-1.3.0.exe` (unsigned local build), SHA-256 `f852be624c9d27f087748532a5ddf30cf3b01d55e28114295e5c394e8229697b`.

## [1.2.1] - 2026-11-21

### Fixed
- **"It didn't add the profiles!"** `BambuStudio.conf` ends with an MD5 trailer after the JSON, which made the JSON parse fail, so no printer was detected and no presets were written. The conf is now parsed with the trailer stripped (never logged: it contains printer access codes).
- Printers are detected from `presets.machine` and `models` in the conf as well as from user printer presets.
- Cleanup is sync-aware (`app.sync_user_preset`): synced presets are neutralised instead of deleted.
- The installer's finish page says how many presets were added, or that no Bambu Lab printer was found.
- Inno Setup script: a line starting with `#13#10` was read as a preprocessor directive.

### Tests
- `test_presets.py` gained a real-conf case using a synthetic `test/fixtures/BambuStudio.conf` with an MD5 trailer and a fake access code: OK.
- Installer `PrintOptimizer-Setup-1.2.1.exe` (unsigned local build), SHA-256 `d1105dddf012ba54e5a740f1fa010decc2485da94e1731619abe9bfe87ce5639`.

## [1.2.0] - 2026-11-21

### Changed
- **Short preset names** `<layer>mm <printer> AI <Goal>` (for example `0.20mm H2S AI Balanced`) instead of `... - Optimized`, for the main system layer heights only (the printer's default and its nearest neighbours, at most 3 per printer and nozzle) × Balanced/Speed/Quality. Nozzles other than 0.4 mm get the size in the name; X1 Carbon is shortened to X1C. *Why:* requested by the owner (short, goal-specific names).
- Cloud-safe migration of 1.x `- Optimized` presets (backed up, then deleted or neutralised if synced); uninstall handles the new set.

### Tests
- `test_presets.py`: 9 presets for the H2S 0.4 (0.16/0.20/0.24 mm × 3 goals), migration and removal cases: OK.

## [1.1.1] - 2026-11-21

### Fixed
- **Presets written to every Bambu Studio user folder**: each signed-in account's `user\<id>\process`, `user\default`, and the active `preset_folder` from `BambuStudio.conf`. *Why:* reported bug: presets went to a folder Bambu Studio doesn't load for a signed-in account, so they didn't appear.
- Legacy presets with the same name are upgraded in place with a backup; the Bambu cloud id and user tweaks are kept, and the preset is marked for upload. A user's own preset with the same name is never changed.
- Uninstall neutralises synced presets instead of deleting them (a deleted cloud preset would be downloaded again, still pointing at the removed exe).

### Tests
- New `test/test_presets.py` (preset creation, upgrade and removal across account folders): OK.

## [1.1.0]
- Progress window, results card, Windows installer, SignPath-ready release workflow (first tracked version in this repository).
