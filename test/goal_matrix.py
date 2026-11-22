"""Goal semantics on the 6 reference prints (run: python3 test/goal_matrix.py [--quick]).

SPEED    time <= original; heat fixed only where it costs no time
BALANCED time <= original + 2 %, fixes most hot layers: at least half of the ones that can be fixed at all
         (= fixed by QUALITY, which may slow to 50 %), unless the +2 % budget is what stops it
QUALITY  thermal + overhang quality first: hot <= balanced, overhangs slowed >= balanced, may add time
ORDER    time(speed) <= time(balanced) <= time(quality)
Every output must pass the built-in validator and test/verify.py (extrusion untouched)."""
import os, sys, json, subprocess, tempfile, re
from concurrent.futures import ProcessPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'src'))
CASES = ['tower_pla', 'tower_petg', 'tower_abs', 'tower_asa', 'speaker_petg', 'speaker_asa']
GOALS = ['speed', 'balanced', 'quality']
EPS = 0.05   # % : time comparisons between goals (estimator noise between different plans)


def accel_at_markers(text):
    """Acceleration in effect at every feature change, AMS/tool-change block (M620/M621) and layer change."""
    cur = None; out = []; mx = 0
    for ln in text.splitlines():
        if ln.startswith('M204'):
            for w in ln.split()[1:]:
                if w[:1] in 'SP':
                    try: cur = float(w[1:]); mx = max(mx, cur)
                    except ValueError: pass
        elif ln.startswith('; FEATURE:') or ln.startswith('M620') or ln.startswith('M621') or ln.startswith('; CHANGE_LAYER'):
            out.append(cur)
    return out, mx


VARIANTS = {'full': {}, 'no_accel': {'accel': False}, 'no_reorder': {'reorder': False}, 'no_hops': {'hops': 'none'},
            'no_reorder_arcs': {'reorder': False, 'arcs': 'on'}}


def run(case, goal, outdir, stress=False, variant='full'):
    import embercheck as B
    from optimizer import Settings
    src = os.path.join(HERE, 'out', case, 'plate_1.gcode')
    text = open(src, encoding='utf-8').read()
    st = Settings(goal=goal, accel=False, max_speedup=1.0) if stress else Settings(goal=goal, **VARIANTS[variant])
    st.dry_run = False
    new, html, s = B.process_text(text, st, case, log=lambda m: None)
    res = {'case': case, 'goal': goal + (' (stress: no speed-ups, no accel)' if stress else ''), 'dt_pct': s['dt_pct'], 'hot_b': s['hot_before'], 'hot_a': s['hot_after'],
           'cold_b': s['cold_before'], 'cold_a': s['cold_after'], 'ov': s['overhangs_slowed'],
           'acc_pct': s['acc_saved_pct'], 'acc_s': s['acc_saved_s'], 'kept_hot': s['budget_kept_hot'],
           'dropped_ov': s['budget_dropped_overhangs'], 'errors': s['errors'], 'verify': None,
           'recs': [r[0] for r in s['recs']], 'variant': variant, 'travel_s': s['travel_saved_s'], 'hop_s': s['hop_saved_s'],
           'hops': s['hops_skipped'], 'retracts': s['retracts_skipped'], 'arcs': s['arcs'], 'arc_segments': s['arc_segments'],
           'bytes': (s['bytes_before'], s['bytes_after']), 'm204_lines': (s['m204_before'], s['m204_after'])}
    if new:
        o = os.path.join(outdir, '%s.%s.%s%s.gcode' % (case, goal, variant, '.stress' if stress else ''))
        open(o, 'w', encoding='utf-8').write(new)
        strict = variant.startswith('no_reorder')
        r = subprocess.run([sys.executable, os.path.join(HERE, 'verify.py'), src, o, '--arc-tol', '0.012'] + ([] if strict else ['--reordered']),
                           capture_output=True, text=True)
        res['verify'] = (r.stdout.strip().splitlines() or ['?'])[-1]
        ma, mxo = accel_at_markers(text); mb, mxn = accel_at_markers(new)
        amax = float(re.search(r'machine_max_acceleration_extruding = (\d+)', text).group(1))
        if ma != mb or mxn > amax:
            res['verify'] = 'ACCEL LEAK (%d marker mismatches, max %d)' % (sum(1 for x, y in zip(ma, mb) if x != y) + abs(len(ma) - len(mb)), mxn)
        res['m204_lines'] = (text.count('\nM204'), new.count('\nM204'))
        os.remove(o)
    return res


def check(rows):
    by = {(r['case'], r['goal']): r for r in rows}
    out = []
    for c in CASES:
        sp, ba, qu = by[(c, 'speed')], by[(c, 'balanced')], by[(c, 'quality')]
        rules = {
            'valid': all(not r['errors'] and r['verify'] == 'PASS' for r in (sp, ba, qu)),
            'speed<=0': sp['dt_pct'] <= 0.0,
            'balanced<=+2%': ba['dt_pct'] <= 2.0,
            'balanced fixes most': (ba['hot_b'] - ba['hot_a']) >= (ba['hot_b'] - qu['hot_a']) / 2 or ba['kept_hot'] > 0,
            'quality hot<=balanced': qu['hot_a'] <= ba['hot_a'],
            'quality ov>=balanced': qu['ov'] >= ba['ov'],
            't(s)<=t(b)<=t(q)': sp['dt_pct'] <= ba['dt_pct'] + EPS and ba['dt_pct'] <= qu['dt_pct'] + EPS,
        }
        out.append((c, rules))
    return out


def feature_table(allrows):
    """Time saved by each feature on the final output = time without it - time with it (negative = it adds time)."""
    by = {(r['case'], r['goal'], r['variant']): r for r in allrows}
    L = ['| Print | Goal | Total | Accel | Travel order | Z-hop/retract skip | Arcs (forced on) | hops / retracts skipped | arcs (segments) | M204 lines | size |',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    for c in CASES:
        for g in GOALS:
            f = by[(c, g, 'full')]; dt = lambda v: by[(c, g, v)]['dt_pct']
            arc = by[(c, g, 'no_reorder_arcs')]
            L.append('| %s | %s | %+.2f%% | %.2f%% | %.2f%% | %.2f%% | %.2f%% | %d / %d | %d (%d) | %d → %d | %+.1f%% |' % (
                c, g, f['dt_pct'], dt('no_accel') - f['dt_pct'], dt('no_reorder') - f['dt_pct'], dt('no_hops') - f['dt_pct'],
                dt('no_reorder') - arc['dt_pct'], f['hops'], f['retracts'], arc['arcs'], arc['arc_segments'],
                f['m204_lines'][0], f['m204_lines'][1], 100.0 * (f['bytes'][1] - f['bytes'][0]) / f['bytes'][0]))
    return '\n'.join(L)


def table(rows, checks):
    L = ['| Print | Goal | Time | of which accel | Hot layers | Cold layers | Overhangs slowed | Valid |',
         '|---|---|---|---|---|---|---|---|']
    for r in rows:
        L.append('| %s | %s | %+.2f%% | %+.2f%% | %d → %d | %d → %d | %d | %s |' % (
            r['case'], r['goal'], r['dt_pct'], -r['acc_pct'], r['hot_b'], r['hot_a'], r['cold_b'], r['cold_a'], r['ov'],
            'PASS' if (not r['errors'] and r['verify'] == 'PASS') else 'FAIL %s %s' % (r['errors'], r['verify'])))
    L += ['', '| Print | ' + ' | '.join(checks[0][1].keys()) + ' |', '|---' * (1 + len(checks[0][1])) + '|']
    for c, rules in checks:
        L.append('| %s | ' % c + ' | '.join('PASS' if v else '**FAIL**' for v in rules.values()) + ' |')
    return '\n'.join(L)


def main():
    outdir = tempfile.mkdtemp()
    jobs = [(c, g, v) for c in CASES for g in GOALS for v in VARIANTS]
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        allrows = list(ex.map(run, [j[0] for j in jobs], [j[1] for j in jobs], [outdir] * len(jobs), [False] * len(jobs),
                              [j[2] for j in jobs]))
    os.makedirs(os.path.join(HERE, 'results'), exist_ok=True)
    json.dump(allrows, open(os.path.join(HERE, 'results', 'goal_matrix_all.json'), 'w'), indent=1)
    for r in allrows:
        if r['errors'] or r['verify'] != 'PASS':
            print('FAIL', r['case'], r['goal'], r['variant'], r['errors'], r['verify'], flush=True)
    rows = [r for r in allrows if r['variant'] == 'full']
    feat = feature_table(allrows)
    # stress: budget must bind and still hold (only slowdowns available -> lowest-value ones are dropped)
    sj = [('tower_pla', 'speed'), ('tower_petg', 'speed'), ('tower_pla', 'balanced')]
    with ProcessPoolExecutor(max_workers=3) as ex:
        stress = list(ex.map(run, [j[0] for j in sj], [j[1] for j in sj], [outdir] * 3, [True] * 3))
    checks = check(rows)
    for c in CASES:
        vs = [r for r in allrows if r['case'] == c and r['variant'] != 'full']
        checks.append(('%s (all variants)' % c, {
            'valid': all(not r['errors'] and r['verify'] == 'PASS' for r in vs),
            'speed<=0': all(r['dt_pct'] <= 0.0 for r in vs if r['goal'] == 'speed'),
            'balanced<=+2%': all(r['dt_pct'] <= 2.0 for r in vs if r['goal'] == 'balanced'),
            'balanced fixes most': True, 'quality hot<=balanced': True, 'quality ov>=balanced': True, 't(s)<=t(b)<=t(q)': True}))
    for r in stress:
        lim = 0.0 if r['goal'].startswith('speed') else 2.0
        checks.append(('%s %s' % (r['case'], r['goal']), {
            'valid': not r['errors'] and r['verify'] == 'PASS', 'speed<=0': r['dt_pct'] <= lim, 'balanced<=+2%': r['dt_pct'] <= 2.0,
            'balanced fixes most': True, 'quality hot<=balanced': True, 'quality ov>=balanced': True,
            't(s)<=t(b)<=t(q)': (not r['hot_a']) or 'Goal' in r['recs']}))
    rows = rows + stress
    md = table(rows, checks) + '\n\n' + feat
    print(md)
    os.makedirs(os.path.join(HERE, 'results'), exist_ok=True)
    json.dump(allrows + stress[0:0], open(os.path.join(HERE, 'results', 'goal_matrix_all.json'), 'w'), indent=1)
    json.dump(rows, open(os.path.join(HERE, 'results', 'goal_matrix.json'), 'w'), indent=1)
    open(os.path.join(HERE, 'results', 'goal_matrix.md'), 'w').write(md + '\n')
    bad = [(c, k) for c, r in checks for k, v in r.items() if not v]
    if bad:
        print('\nFAILED:', bad); sys.exit(1)
    print('\ngoal_matrix: all rules PASS')


if __name__ == '__main__':
    main()
