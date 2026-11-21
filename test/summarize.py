import sys, json; sys.path.insert(0, '/workspace/print-optimizer/src')
from bambu_optimizer import process_text
from optimizer import Settings
rows = []
cases = ['tower_pla', 'tower_petg', 'tower_abs', 'tower_asa', 'speaker_petg', 'speaker_asa']
for c in cases:
    txt = open('/workspace/print-optimizer/test/results/%s.gcode' % c).read()
    for label, kw in [('default', {}), ('reorder+fix-strings', dict(reorder=True, fix_strings=True))]:
        st = Settings(**kw); st.dry_run = False
        new, html, s = process_text(txt, st, c, lambda m: None)
        rs = s['reorder']; tr = s['travel']; ov = s['ov']
        rows.append(dict(case=c, mode=label, bambu=s['bambu_time'], before_min=round(s['t_before'] / 60, 2), after_min=round(s['t_after'] / 60, 2),
                         dt_pct=round(s['dt_pct'], 2), hot=f"{s['hot_before']}->{s['hot_after']}", cold=f"{s['cold_before']}->{s['cold_after']}",
                         f_changed=s['est']['f_changed'], fan_changed=s['est']['fan_changed'], fan_inserted=s['est']['fan_inserted'],
                         travel_reorder_mm=f"{rs['travel_before']:.0f}->{rs['travel_after']:.0f}", open_air=tr['open_air'],
                         open_air_unretracted=tr['open_air_unretracted'], strings_fixed=tr['fixed'],
                         overhang_extra=ov.get('b2', 0) + ov.get('b3', 0) + ov.get('b4', 0), overhang_slowed=ov.get('slowed', 0),
                         flow_limited=round(s['flow_limited_share'], 2), errors=s['errors'], secs=round(s['seconds'], 1)))
        print(json.dumps(rows[-1]), flush=True)
json.dump(rows, open('/workspace/print-optimizer/test/results/summary.json', 'w'), indent=1)
