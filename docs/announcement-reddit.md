<!-- Draft text for a Reddit post (r/BambuLab). Not posted. -->
# EmberCheck 1.4.2 — free, local print optimizer for Bambu Studio (formerly "Bambu Print Optimizer")

I've been building a free, open-source (MIT) post-processor for Bambu Studio. It used to be called "Bambu Print Optimizer" and is now **EmberCheck**.

**What it does.** Slice as usual with an "EmberCheck Balanced / Speed / Quality" process preset. EmberCheck then:
- runs a thermal check of every layer (Helio-style, but a simple local model, not a calibrated simulation)
- slows layers that are too hot and speeds up cool ones within your filament's flow limit
- raises acceleration on infill and inner walls
- re-orders infill islands and skips needless Z-hops on short infill travels

The extrusion is never changed: every file is checked before it is written.

**The goals keep their promises** (checked by tests on every build): Speed is never slower, Balanced adds at most +2% while fixing most hot layers, and Quality puts quality first.

**Numbers** (six H2S test prints, the optimizer's motion model scaled to Bambu's own estimate, not stopwatch-measured prints yet):
- Speed: −3.4% to −16.3% print time
- Balanced: −0.9% to −9.8%. For example, a PETG speaker adapter went from 2h 45m to 2h 29m (−16m)
- Quality: −0.7% to +3.5%, with more overhangs slowed

**New since 1.1.0:**
- Works with **every Bambu Lab printer and nozzle**: the installer reads the model list from Bambu Studio's own profiles and pre-checks the printers you have set up.
- **Print time in hours and minutes** on the results card. The printer's progress and remaining time (M73) are updated too.
- Each optimized file carries a **stamp** with a SHA-256 hash, so you can check that the file you print is the one EmberCheck wrote (`EmberCheck.exe --check-stamp`).
- From Bambu Studio's source: Print, Send and Export all use the post-processed file, and the preview shows it. Bambu's own time estimate in the slice panel stays from before the optimization.
- Upgrades the old version in place, keeping your preset tweaks.

**Download:** https://github.com/drewrobinso/embercheck/releases/tag/v1.4.2. It's a Windows installer with no Python needed and nothing uploaded anywhere. There is also a Python zip for other systems.

⚠️ This preview build is **not code-signed yet** (SignPath Foundation signing is pending). SmartScreen will say "Windows protected your PC": click *More info* → *Run anyway*. If Smart App Control is on, it blocks the installer completely, so use the Python zip or wait for the signed build. The SHA-256 values are on the release page.

Source, docs and changelog: https://github.com/drewrobinso/embercheck

Tested on Bambu Studio 02.09.01.70 slices (H2S) and on my own Windows PC. Profile handling is tested for the other printers, but not yet on real prints. Feedback very welcome, especially from X1/P1/A1 owners.

It's free and stays free. If it saves you time or filament: https://buymeacoffee.com/drewrobinso
