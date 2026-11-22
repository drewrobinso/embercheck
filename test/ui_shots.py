"""Render the results cards and the progress window at simulated 100/125/150/200 % display scaling and assert
that every button is fully visible and the window fits the screen. Needs an X display (Xvfb) and Pillow.
usage: DISPLAY=:78 python3 test/ui_shots.py [outdir]"""
import os, sys, json, subprocess, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(os.path.dirname(HERE), 'src')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), 'screens', 'ui_scaling')
LONG = [
    ['Goal', 'Speed goal keeps print time at or below the original, so 37 layers predicted too hot were left as they are (layers 12, 13, 14, 15, 16, 17, 18, 19 and 29 more). Use the <b>EmberCheck Balanced or EmberCheck Quality</b> preset for this print to fix them, or apply the cooling settings below.'],
    ['Cooling / min layer time', 'Bambu Studio &rsaquo; Filament &rsaquo; Cooling: <b>Slow printing down for better layer cooling</b> (slow_down_layer_time) is 4s. 135 layers are predicted too hot. Raising it to ~11s, printing 2+ copies at once, or adding a sacrificial "cooling tower" next to small parts fixes this at the source.'],
    ['Stringing / travel', '1873 of 4211 travels (10342 mm total) cross open air. Enable <b>Avoid crossing wall</b> (Process &rsaquo; Others; reduce_crossing_wall) so travels stay inside the part, which this post-processor cannot safely re-route.'],
]
CARDS = {
    # numbers from the speaker_petg H2S test slice, Balanced goal (1.4.2)
    'optimized': {'status': 'optimized', 'name': 'Bambu Studio slice', 'goal': 'balanced', 'dt_pct': -9.8, 'from_bambu': True,
                  'bambu_time': '2h 45m 7s', 'time_before_s': 9907, 'time_after_s': 8932,
                  'time_source': "Bambu Studio estimate, scaled by EmberCheck's motion model",
                  'feature_saved_s': {'acceleration': 241, 'hop/retract skip': 544, 'travel order': 3, 'speed/cooling/overhang feeds': 187},
                  'hot_before': 0, 'hot_after': 0, 'cold_before': 100, 'cold_after': 88,
                  'overhang_adjusted': 1965, 'open_air': 1873, 'open_air_unretracted': 4, 'acc_saved_s': 230, 'acc_saved_pct': 2.4,
                  'travel_saved_s': 3, 'travel_saved_mm': 41, 'hops_skipped': 4959, 'retracts_skipped': 0, 'hop_saved_s': 519,
                  'arcs_on': False, 'arcs_note': 'H2S does its own curve planning, Bambu Studio turns arc fitting off for it too',
                  'recommendations': LONG, 'report': '/tmp/none.html'},
    'failed': {'status': 'failed', 'from_bambu': True, 'name': 'tower_asa.gcode.3mf :: plate_1.gcode', 'goal': 'speed', 'dt_pct': 0.0,
               'errors': ['layer 37: set of extrusion moves changed', 'extrusion per layer changed (max diff 0.000120 mm) - the original G-code was kept and nothing was written; please send the log folder with this file'],
               'recommendations': LONG[1:], 'report': None, 'log_dir': '/tmp'},
    'nochange': {'status': 'nochange', 'name': 'calibration_cube.gcode', 'goal': 'quality', 'dt_pct': 0.0,
                 'recommendations': [['Slicer settings', 'Nothing important to change in the slicer for this print.']]},
}
PROG = r'''
import sys, time; sys.path.insert(0, %r)
import ui
def work(cb, cancel):
    for i in range(40):
        cb('Optimizing', i / 40.0, 'layer %%d/1360' %% (i * 34)); time.sleep(0.05)
    return 1
ui.ProgressWindow('Speaker enclosure v3 final (2) with a rather long project name.gcode.3mf').run(work)
''' % SRC
PRN = r'''
import sys; sys.path.insert(0, %r)
import ui, bambu_presets as bp
avail = bp.available_models(%r) or [(m, m, []) for m in bp.FALLBACK_MODELS]
ui.choose_printers(avail, {'Bambu Lab H2S', 'Bambu Lab X1 Carbon'})
''' % (SRC, os.environ.get('EMBERCHECK_SYSDIR', '/workspace/winbuild/prefix/drive_c/users/box/AppData/Roaming/BambuStudio/system'))


def main():
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp(); results = []
    for sc in ('1.0', '1.25', '1.5', '2.0'):
        env = dict(os.environ, PO_TK_SCALING=sc)
        for name, card in CARDS.items():
            p = os.path.join(tmp, name + '.json'); json.dump(card, open(p, 'w'))
            shot = os.path.join(OUT, 'card_%s_%d.png' % (name, round(float(sc) * 100)))
            env['PO_UI_SHOT'] = shot
            subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, %r); import ui; ui.show_summary(%r, auto_close=0)' % (SRC, p)],
                           env=env, timeout=60, check=True)
            results.append(json.load(open(shot + '.json')))
        shot = os.path.join(OUT, 'printers_%d.png' % round(float(sc) * 100))
        env['PO_UI_SHOT'] = shot
        subprocess.run([sys.executable, '-c', PRN], env=env, timeout=60, check=True)
        results.append(json.load(open(shot + '.json')))
        shot = os.path.join(OUT, 'progress_%d.png' % round(float(sc) * 100))
        env['PO_UI_SHOT'] = shot
        subprocess.run([sys.executable, '-c', PROG], env=env, timeout=60, check=True)
        results.append(json.load(open(shot + '.json')))
    bad = [r for r in results if not r['ok']]
    for r in results:
        print('%-18s scaling %-5s window %-22s buttons %s  %s' % (r['tag'], r['scaling'], r['window'],
              [b[:4] for b in r['buttons']], 'OK' if r['ok'] else 'CLIPPED'))
    for f in os.listdir(OUT):
        if f.endswith('.png.json'): os.remove(os.path.join(OUT, f))
    if bad:
        print('FAILED: %d windows clip' % len(bad)); sys.exit(1)
    print('ui_shots: all %d windows OK, screenshots in %s' % (len(results), OUT))


if __name__ == '__main__':
    main()
