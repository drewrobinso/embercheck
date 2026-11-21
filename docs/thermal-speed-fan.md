# Thermal model, hot-layer fixes and speed-ups

## What it does
- Splits each layer into islands (union of the extrusion paths, shapely).
- Estimates each island's surface temperature when the next layer goes on top: it decays toward the chamber temperature with a time constant that shrinks with part-fan speed, is re-heated by each new layer, and carries heat to islands above through their overlap.
- Compares it with the material window from `src/materials.py` (for example PLA 30–70 °C, PETG 45–92 °C, ASA 68–120 °C) plus a safety margin (Speed/Balanced 3 °C, Quality 5 °C).
- **Too hot:** raise the part fan first, where the material allows it (free on Speed/Balanced), then slow the layer down within Bambu's minimum speed.
- **Cool with headroom:** speed up inner walls, infill and support (Speed up to 1.5×, Balanced 1.25×, Quality none). Outer walls and top surfaces are never sped up. Every feed stays inside the filament's max volumetric flow and the machine limits.
- **ABS/ASA too cold:** less fan.

## Never touched
Temperatures, E values, the first 2 layers' speeds, start/end G-code, AMS / firmware conditional blocks.

## Limits
The model is lumped and uncalibrated: use it to compare layers and before/after, not as measured °C. See the README section *How the thermal model works*.

## Results (1.4.0)
Hot layers before → after: tower PLA 101 → 2, tower PETG 44 → 0, tower ASA 98 → 96 (spire already at the minimum speed and fan cap), tower ABS and speakers 0 → 0.
