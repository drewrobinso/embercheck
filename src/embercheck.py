#!/usr/bin/env python3
"""EmberCheck (formerly Bambu Print Optimizer) - free, local, Helio-style thermal check + speed/fan/travel optimiser
for Bambu Studio G-code and (since 1.5) PrusaSlicer G-code for Marlin printers such as the Creality Ender 3 V2 Neo.

Bambu Studio post-processing usage (Process > Others > Post-processing scripts):
    "C:\\Path\\To\\python.exe" "C:\\Path\\To\\embercheck.py" --goal balanced
PrusaSlicer (Print Settings > Output options > Post-processing scripts), same line.
Both slicers append the temporary G-code path as the last argument; the file is edited in place.

Standalone:
    python embercheck.py model.gcode -o model.opt.gcode
    python embercheck.py plate.gcode.3mf            (writes plate.optimized.gcode.3mf)
    python embercheck.py model.gcode --dry-run --open   (report only)
"""
import argparse, os, sys, time, datetime, hashlib, io, zipfile, re, traceback, webbrowser, shutil, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gcode_model import GcodeFile, Kinematics, estimate_times, UnsupportedGcode  # noqa: E402
from optimizer import Optimizer, Settings, HAVE_GEOM, GEOM_ERROR, ACCEL_FEATURES, ACCEL_MIN_LAYER, CURVE_PLANNING_MODELS  # noqa: E402
from emitter import emit, validate, rewrite_m73  # noqa: E402
import stamp  # noqa: E402
from project_info import REPO_URL  # noqa: E402
import report as R  # noqa: E402
from progress import Progress, Cancelled, noop  # noqa: E402

VERSION = '1.5.0'
APP = 'EmberCheck'


def windows_documents_dir():
    """Real Documents folder (follows OneDrive / folder redirection)."""
    try:
        import ctypes
        from ctypes import wintypes
        class GUID(ctypes.Structure):
            _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]
        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(p)) == 0:
            path = p.value
            ctypes.windll.ole32.CoTaskMemFree(p)
            if path and os.path.isdir(path):
                return path
    except Exception:
        pass
    try:
        import winreg
        for sub in (r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders',
                    r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                v, _ = winreg.QueryValueEx(k, 'Personal')
                v = os.path.expandvars(v)
                if v and os.path.isdir(v):
                    return v
    except Exception:
        pass
    return None


def _adopt_dir(new, olds):
    """Move an older product folder to its new name once (1.x BambuPrintOptimizer -> EmberCheck).
    If the new folder already exists, the old folder's files are merged in (existing files win; runs.log appended)."""
    for old in olds:
        if not os.path.isdir(old):
            continue
        try:
            if not os.path.exists(new):
                os.rename(old, new); continue
            for root, _dirs, files in os.walk(old, topdown=False):
                dst = os.path.join(new, os.path.relpath(root, old))
                os.makedirs(dst, exist_ok=True)
                for f in files:
                    sp, dp = os.path.join(root, f), os.path.join(dst, f)
                    if f == 'runs.log' and os.path.exists(dp):
                        with open(sp, encoding='utf-8', errors='replace') as a_, open(dp, 'a', encoding='utf-8') as b_:
                            b_.write(a_.read())
                        os.remove(sp)
                    elif not os.path.exists(dp):
                        os.replace(sp, dp)
                try:
                    os.rmdir(root)
                except OSError:
                    pass
        except OSError:
            pass
    return new


def default_report_dir():
    home = os.path.expanduser('~')
    docs = windows_documents_dir() if sys.platform == 'win32' else None
    if not docs:
        docs = os.path.join(home, 'Documents')
    base = docs if os.path.isdir(docs) else home
    new = os.path.join(base, 'EmberCheck')
    _adopt_dir(new, [os.path.join(base, 'BambuPrintOptimizer')])   # 1.x reports
    return os.path.join(new, 'reports')


def local_data_dir():
    """%LOCALAPPDATA%\\EmberCheck on Windows (receipt log),
    ~/.local/share/embercheck elsewhere."""
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
        return _adopt_dir(os.path.join(base, 'EmberCheck'), [])
    base = os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
    return _adopt_dir(os.path.join(base, 'embercheck'), [])


def _icon(root):
    try:
        import ui
        ui.set_app_icon(root)
    except Exception:
        pass


def stamp_lines(k, st, g):
    """Text of the EmberCheck block (see stamp.py): plain ASCII comments."""
    fs = k.get('feature_saved_s', {})
    saved = ', '.join('%s %s%s' % (n, '-' if v > 0 else '+', R.fmt_dur(v)) for n, v in fs.items() if abs(v) >= 0.5) or 'none'
    arcs = ('arcs: %d arcs replace %d moves' % (k.get('arcs', 0), k.get('arc_segments', 0))) if k.get('arcs_on') else \
        'arcs: off (%s)' % (k.get('arcs_note') or 'off')
    lim = ('not slower than the original' if st.time_budget == 0 else
           ('+%g%%' % (100 * st.time_budget) if st.time_budget is not None else 'none, quality first'))
    return ['%s %s - print optimizer for %s (%s)' % (APP, VERSION, g.dialect.slicer, REPO_URL),
            'date: %s' % datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %z'),
            'goal: %s (time limit: %s)' % (st.goal, lim),
            'print time: %s [%s]' % (R.time_line(k['time_before_s'], k['time_after_s'], '-', '->'), k['time_source']),
            'by feature: %s' % saved,
            arcs,
            'changes: %d feeds, %d fan, %d M204 raised, %d Z-hops / %d retracts skipped, %d overhang segments slowed, %s' % (
                k['est'].get('f_changed', 0), k['est'].get('fan_changed', 0) + k['est'].get('fan_inserted', 0),
                k['est'].get('acc_raised', 0), k.get('hops_skipped', 0), k.get('retracts_skipped', 0), k.get('overhangs_slowed', 0),
                'M73 progress and remaining time updated' if g.dialect.name == 'bambu' or k.get('m73_updated') else
                'no M73 progress lines in the file'),
            'thermal model: hot layers %d -> %d, cold layers %d -> %d' % (k['hot_before'], k['hot_after'], k['cold_before'], k['cold_after']),
            ('checked: same layers, same extrusion per layer (exact), start/end/AMS/timelapse G-code unchanged' if g.dialect.name == 'bambu' else
             'checked: same layers, same extrusion per layer (exact), start/end/custom G-code and %s footer unchanged' % g.dialect.slicer),
            'verify: EmberCheck.exe --check-stamp FILE.gcode|FILE.3mf  (docs/verify.md)']


def eprint(*a):
    """print() that is safe under pythonw.exe (no console => sys.stderr is None)."""
    if sys.stderr is not None:
        try:
            print(*a, file=sys.stderr)
        except Exception:
            pass


def body_time(g, kin):
    body = g.lines[g.body_start:g.body_end]
    d, _ = estimate_times(body, kin)
    return sum(d)


def process_text(text, st, name, log, progress=noop):
    """Returns (new_text or None, report_html, summary)."""
    t0 = time.time()
    progress('parse', 0.0)
    g = GcodeFile(text, progress=progress)
    opt = Optimizer(g, st, log=log, progress=progress).run()
    kin = Kinematics(g)
    tb = body_time(g, kin)

    def build():
        out, est = emit(opt, progress=progress)
        m73n = 0
        if st.m73:
            out, m73n = rewrite_m73(g, out, opt.kin, progress=progress)
        errs, metrics = validate(g, out, opt, progress=progress)
        ng = GcodeFile(out) if not errs else None
        ta = body_time(ng, kin) if ng else tb
        return out, est, m73n, errs, metrics, ta
    out, est, m73n, errs, metrics, ta = build()
    # the goal's time limit is checked on the real output (same estimator as the card / M73), not just the plan
    tries = 0
    while st.time_budget is not None and not errs and tb and ta > tb * (1 + st.time_budget) and tries < 4:
        tries += 1
        over = ta - tb * (1 + st.time_budget)
        log('time budget: output %.1fs over the %s limit, trimming more' % (over, st.goal))
        left = opt.enforce_budget(st.time_budget, extra_s=-getattr(opt, 'credit_s', 0.0) + over * 1.5 + 0.0005 * tb)
        opt.accel_savings()
        out, est, m73n, errs, metrics, ta = build()
        if left > 0 and ta > tb * (1 + st.time_budget):
            break
    bt = g.slicer_time      # PrusaSlicer: '; estimated printing time (normal mode) = ...' in the footer
    if bt is None:
        for ln in g.raw_lines[:30]:
            mm = re.search(r'model printing time:\s*([^;]+)', ln)
            if mm: bt = mm.group(1).strip(); break
    slicer = g.dialect.slicer
    hi = opt.mat['t_high']
    hot_b = sum(1 for e in opt.base if e.Tmax is not None and e.Tmax > hi)
    hot_a = sum(1 for e in opt.opt if e.Tmax is not None and e.Tmax > hi)
    cold_b = sum(1 for e in opt.base if e.cold_frac >= 0.25)
    cold_a = sum(1 for e in opt.opt if e.cold_frac >= 0.25)
    need = [opt.opt[i].time for i in range(opt.nl) if opt.base[i].Tmax is not None and opt.base[i].Tmax > hi]
    cat, flow_lim, ext_t = R.time_breakdown(opt)
    bs = getattr(opt, 'budget_stats', {}) or {}
    rs = opt.reorder_stats; hs = getattr(opt, 'hop_stats', {}) or {}
    dec = opt.decisions
    sped = sum(1 for d in dec if d.startswith('speed') or (d.startswith('cold->s') and not d.startswith('cold->s1.00')))
    slowed = sum(1 for d in dec if d.startswith('hot->s') and not d.startswith('hot->s1.00')) + dec.count('hot-residual')
    fanl = sum(1 for d in dec if 'fan' in d) + dec.count('hot-residual')
    pm = g.config.get('printer_model', '') or ''
    arcs_why = ('%s does its own curve planning, Bambu Studio turns arc fitting off for it too' % (re.sub(r'^Bambu Lab ', '', pm) or 'this printer')
                if any(m in pm for m in CURVE_PLANNING_MODELS) and g.dialect.name == 'bambu' else 'the printer profile has arc fitting off')
    # raw times: Bambu Studio's own estimate from the header, scaled by our model's new/old ratio (one model for both)
    bambu_s = R.parse_hms(bt)
    scale = (bambu_s / tb) if (bambu_s and tb) else 1.0
    t_src = '%s estimate, scaled by EmberCheck\'s motion model' % slicer if bambu_s and tb else 'EmberCheck\'s motion model'
    disp_b, disp_a = (bambu_s, ta * scale) if bambu_s and tb else (tb, ta)
    feat_s = {'acceleration': getattr(opt, 'acc_saved', 0.0) * scale,
              'hop/retract skip': (hs.get('time_saved', 0.0) if st.hops else 0.0) * scale,
              'travel order': (rs.get('time_saved', 0.0) if st.reorder else 0.0) * scale}
    feat_s['speed/cooling/overhang feeds'] = (disp_b - disp_a) - sum(feat_s.values())
    changes = [
        'Print time: %s [%s]' % (R.time_line(disp_b, disp_a, '-', '&rarr;'), t_src),
        '%d layers sped up (inner walls / infill only, max %.2fx, flow-limited to %g mm&sup3;/s)' % (sped, st.max_speedup, opt.max_vol),
        '%d layers slowed for cooling, %d layers with fan adjusted' % (slowed, fanl),
        '%d feedrate values changed, %d existing fan commands changed, %d fan commands inserted (overhang/bridge boost + restore)' % (
            est['f_changed'], est['fan_changed'], est['fan_inserted']),
        '%d wall segments slowed for overhangs not marked by the slicer' % len(opt.ovf),
        'Acceleration raised on %d layers (%s, up to %d mm/s&sup2;; outer walls, overhangs, bridges, top surfaces and the first %d layers keep the slicer\'s value): %s' % (
            getattr(opt, 'acc_layers', 0), ', '.join(sorted(ACCEL_FEATURES[st.goal])).lower(), getattr(opt, 'acc_target_max', 0), ACCEL_MIN_LAYER,
            R.fmt_t(getattr(opt, 'acc_saved', 0.0)) + ' saved') if getattr(opt, 'acc_layers', 0) else 'Acceleration unchanged',
        ('Goal %s: print time limit %s; %d cooling slowdowns and %d overhang slowdowns were dropped to stay within it' % (
            st.goal, 'not slower than the original' if st.time_budget == 0 else '+%g%%' % (100 * st.time_budget),
            bs.get('kept_hot_layers', 0), bs.get('dropped_overhangs', 0))) if st.time_budget is not None else
        'Goal quality: no print-time limit, thermal and overhang quality first',
        '%d anti-string retractions added' % opt.travel['fixed'],
        ('Smart travel order: %d infill runs re-ordered (nearest neighbour + 2-opt), travel %.0f &rarr; %.0f mm, ~%s saved' % (
            rs['reordered_runs'], rs['travel_before'], rs['travel_after'], R.fmt_t(rs.get('time_saved', 0.0))) if st.reorder else 'Travel order unchanged'),
        ('Z-hops skipped on %d short in-infill travels, retract+wipe pairs skipped on %d (net E unchanged), ~%s saved' % (
            hs.get('hops_skipped', 0), hs.get('retracts_skipped', 0), R.fmt_t(hs.get('time_saved', 0.0))) if st.hops else 'Z-hops and retractions unchanged'),
        ('Arc fitting: %d arcs replace %d G1 segments (tolerance %g mm, exact E)' % (est.get('arcs', 0), est.get('arc_segments', 0),
            st.arc_tol or min(0.05, max(0.005, g.cfg('resolution', 0.01) or 0.01))) if getattr(opt, 'arcs_on', False) else
         'Arc fitting off (%s)' % (arcs_why if st.arcs == 'auto' else 'turned off')),
        '%d M73 remaining-time values updated' % m73n,
        'Nothing else touched: no temperatures, extrusion per layer exactly the same (skipped retract/un-retract pairs and arcs keep the exact E sum), no start/end/AMS/timelapse G-code.'
        if g.dialect.name == 'bambu' else
        'Nothing else touched: no temperatures, extrusion per layer exactly the same (skipped retract/un-retract pairs and arcs keep the exact E sum), no start/end/custom G-code, %s footer and config unchanged.' % slicer]
    summary = {'m73_updated': m73n, 't_before': tb, 't_after': ta, 'dt_pct': 100 * (ta - tb) / tb if tb else 0, 'bambu_time': bt,
               'goal': st.goal, 'time_budget_pct': None if st.time_budget is None else 100 * st.time_budget,
               'acc_saved_s': getattr(opt, 'acc_saved', 0.0), 'acc_saved_pct': 100 * getattr(opt, 'acc_saved', 0.0) / tb if tb else 0,
               'acc_layers': getattr(opt, 'acc_layers', 0), 'acc_moves': est.get('acc_moves', 0),
               'acc_target_max': getattr(opt, 'acc_target_max', 0),
               'budget_kept_hot': bs.get('kept_hot_layers', 0), 'budget_dropped_overhangs': bs.get('dropped_overhangs', 0),
               'overhangs_slowed': len(opt.ovf),
               'reorder_runs': rs.get('reordered_runs', 0) if st.reorder else 0,
               'travel_saved_mm': (rs['travel_before'] - rs['travel_after']) if st.reorder else 0.0,
               'travel_saved_s': rs.get('time_saved', 0.0) if st.reorder else 0.0,
               'hops_skipped': hs.get('hops_skipped', 0), 'retracts_skipped': hs.get('retracts_skipped', 0),
               'hop_saved_s': hs.get('time_saved', 0.0),
               'arcs_on': bool(getattr(opt, 'arcs_on', False)), 'arcs': est.get('arcs', 0), 'arc_segments': est.get('arc_segments', 0),
               'arcs_note': '' if getattr(opt, 'arcs_on', False) else (arcs_why if st.arcs == 'auto' else 'turned off'),
               'time_before_s': disp_b, 'time_after_s': disp_a, 'time_source': t_src, 'feature_saved_s': feat_s,
               'time_line': R.time_line(disp_b, disp_a),
               'bytes_before': len(text), 'bytes_after': len(out) if out else len(text),
               'm204_before': text.count('\nM204'), 'm204_after': out.count('\nM204') if out else 0,
               'hot_before': hot_b, 'hot_after': hot_a, 'cold_before': cold_b, 'cold_after': cold_a,
               'hot_layer_time_needed': int(max(need) + 0.999) if need else None, 'breakdown': cat,
               'flow_limited_share': flow_lim / ext_t if ext_t else 0,
               'accel_share': cat['Extrusion accel/decel loss'] / ext_t if ext_t else 0,
               'changes': changes, 'errors': errs, 'metrics': metrics, 'seconds': time.time() - t0,
               'travel': opt.travel, 'reorder': opt.reorder_stats, 'ov': getattr(opt, 'ov_stats', {}),
               'material': opt.mat_name, 'layers': opt.nl, 'est': est, 'slicer': slicer,
               'printer_model': pm}
    summary['n_edits'] = est['f_changed'] + est['fan_changed'] + est['fan_inserted'] + est['f_inserted'] + est['acc_inserted'] + \
        est.get('acc_raised', 0) + est.get('lines_skipped', 0) + est.get('arcs', 0) + opt.travel['fixed'] + (1 if opt.order and st.reorder else 0)
    if out and not errs and summary['n_edits']:
        validated = out
        out = stamp.insert(out, stamp_lines(summary, st, g))
        if stamp.strip(out)[0] != validated:      # the stamp must be the only difference to the validated file
            errs.append('internal: stamp changed the G-code'); summary['errors'] = errs
        summary['body_sha256'] = stamp.body_sha256(validated)
        summary['bytes_after'] = len(out)
    applied = (not errs) and not st.dry_run
    desc = 'goal=%s, max speed-up %.2fx, %s%s%s' % (st.goal, st.max_speedup, 'reorder on, ' if st.reorder else '',
                                                   'fix-strings on, ' if st.fix_strings else '', 'v' + VERSION)
    html = R.build(opt, summary, {'errors': errs, 'metrics': metrics}, applied, name, desc)
    summary['hot_after'] = hot_a
    summary['recs'] = R.recommendations(opt, summary)
    summary['overhang_adjusted'] = len(opt.ovf) + len(opt.boost)
    progress('verify', 1.0)
    return (out if not errs else None), html, summary


def already_stamped(text, st, name, log):
    """A file that already carries an EmberCheck stamp is never optimized twice (e.g. Bambu's print-host upload runs the
    post-processing scripts again on the exported copy). Returns (None, html, summary) or None."""
    _, block = stamp.strip(text)
    if block is None:
        return None
    first = stamp.fields(block)
    log('%s already carries an EmberCheck stamp - left unchanged' % name)
    msg = 'This G-code was already optimized by EmberCheck (%s), so it was left unchanged.' % (first.get('goal') or 'stamp found')
    summ = {'errors': [], 'n_edits': 0, 'goal': st.goal, 'dt_pct': 0.0, 'recs': [('Goal', msg)], 'already': True,
            'hot_before': 0, 'hot_after': 0, 'cold_before': 0, 'cold_after': 0, 'seconds': 0.0}
    html = '<!doctype html><meta charset="utf-8"><title>EmberCheck report - %s</title><h1>EmberCheck report</h1><p>%s</p><pre>%s</pre>' % (
        R.html.escape(name), R.html.escape(msg), R.html.escape(block))
    return None, html, summ


def card_data(summ, name, report_path, dry_run):
    errs = summ.get('errors') or []
    if errs:
        status = 'failed'
    elif dry_run:
        status = 'dryrun'
    elif not summ.get('n_edits'):
        status = 'nochange'
    else:
        status = 'optimized'
    order = {'Goal': -1, 'Cooling / min layer time': 0, 'Chamber / cold layers': 1, 'Stringing / travel': 2, 'Overhangs': 3, 'Bridges': 4}
    recs = sorted(summ.get('recs') or [], key=lambda r: order.get(r[0], 9))
    return {'status': status, 'name': name, 'dt_pct': summ.get('dt_pct', 0.0), 'bambu_time': summ.get('bambu_time'),
            'hot_before': summ.get('hot_before', 0), 'hot_after': summ.get('hot_after', 0),
            'cold_before': summ.get('cold_before', 0), 'cold_after': summ.get('cold_after', 0),
            'overhang_adjusted': summ.get('overhang_adjusted', 0), 'goal': summ.get('goal'),
            'acc_saved_s': summ.get('acc_saved_s', 0.0), 'acc_saved_pct': summ.get('acc_saved_pct', 0.0),
            'travel_saved_s': summ.get('travel_saved_s', 0.0), 'travel_saved_mm': summ.get('travel_saved_mm', 0.0),
            'hops_skipped': summ.get('hops_skipped', 0), 'retracts_skipped': summ.get('retracts_skipped', 0),
            'hop_saved_s': summ.get('hop_saved_s', 0.0), 'arcs_on': summ.get('arcs_on', False), 'arcs': summ.get('arcs', 0),
            'arc_segments': summ.get('arc_segments', 0), 'arcs_note': summ.get('arcs_note', ''),
            'm204_before': summ.get('m204_before', 0), 'm204_after': summ.get('m204_after', 0),
            'bytes_before': summ.get('bytes_before', 0), 'bytes_after': summ.get('bytes_after', 0),
            'open_air': summ.get('travel', {}).get('open_air', 0),
            'open_air_unretracted': summ.get('travel', {}).get('open_air_unretracted', 0),
            'recommendations': [list(r) for r in recs[:3]], 'report': report_path, 'errors': errs,
            'seconds': summ.get('seconds'),
            'time_before_s': summ.get('time_before_s'), 'time_after_s': summ.get('time_after_s'),
            'time_source': summ.get('time_source', ''), 'feature_saved_s': summ.get('feature_saved_s', {}),
            'body_sha256': summ.get('body_sha256', '')}


def log_run(src, card, runs_log=None):
    """Receipt line in %LOCALAPPDATA%\\EmberCheck\\runs.log (tab separated): when, file, goal, before -> after, delta, hash."""
    if not card or card.get('status') != 'optimized':
        return
    try:
        path = runs_log or os.path.join(local_data_dir(), 'runs.log')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        b, t = card.get('time_before_s') or 0, card.get('time_after_s') or 0
        line = '\t'.join([datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z'), 'EmberCheck ' + VERSION, src,
                          'goal=' + str(card.get('goal')), R.time_line(b, t, '-', '->'), card.get('time_source', ''),
                          'body_sha256=' + card.get('body_sha256', '')])
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def gui_available():
    if sys.platform != 'win32' and not os.environ.get('DISPLAY'):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def spawn_summary(json_path, pos=None, auto_close=60):
    """Show the results card in a separate, detached process so this script can exit and Bambu Studio continues."""
    exe = sys.executable
    frozen = getattr(sys, 'frozen', False)          # PyInstaller build: the exe *is* the program
    script = [] if frozen else [os.path.abspath(__file__)]
    args_tail = ['--show-summary', json_path, '--auto-close', str(auto_close)]
    if pos:
        args_tail += ['--pos', '%d,%d' % pos]
    if sys.platform == 'win32':
        w = os.path.join(os.path.dirname(exe), 'pythonw.exe')
        if not frozen and os.path.exists(w):
            exe = w
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([exe] + script + args_tail, creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen([exe] + script + args_tail, start_new_session=True, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _open_path(p):
    try:
        if sys.platform == 'win32':
            os.startfile(p)  # noqa
        else:
            webbrowser.open('file://' + os.path.abspath(p))
    except Exception:
        pass


def app_dir():
    return os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))


def pick_file():
    """Start-menu launch without a file: ask for a sliced plate (.gcode.3mf) or G-code."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk(); r.withdraw(); _icon(r)
        p = filedialog.askopenfilename(title='EmberCheck - choose a sliced plate',
                                       filetypes=[('Sliced plate / G-code', '*.3mf *.gcode'), ('All files', '*.*')])
        r.destroy()
        return p or None
    except Exception:
        return None


def printer_choices(bp, bambu_dir, sysdir, manifest):
    """(available [(model, short, machines)], pre-checked models): printers set up in Bambu Studio plus the models
    chosen last time."""
    data_dir = bambu_dir or bp.bambu_data_dir()
    avail = bp.available_models(sysdir)
    found = set(bp.model_of(n, sysdir) for n in bp.installed_printers(data_dir, sysdir))
    prev = (bp._load(manifest) or {}).get('models') or []
    return avail, [m for m, _, _ in avail if m in found or m in prev]


def list_printers(a):
    """--list-printers FILE: one line per model 'model|short|1 if pre-selected|nozzles' (read by the installer's printer page)."""
    import bambu_presets as bp
    data_dir = a.bambu_dir or bp.bambu_data_dir()
    sysdir = bp.system_profiles_dir(data_dir)
    lines = []
    if sysdir:
        avail, pre = printer_choices(bp, a.bambu_dir, sysdir, os.path.join(app_dir(), 'presets_manifest.json'))
        noz = lambda ms: ', '.join(sorted({x.group(1) for n in ms for x in [re.search(r'(\d+(?:\.\d+)?) nozzle', n)] if x}, key=float))
        lines = ['%s|%s|%d|%s' % (m, short, 1 if m in pre else 0, noz(ms)) for m, short, ms in avail]
    with open(a.list_printers, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + ('\n' if lines else ''))
    return 0


def prusa_presets_cmd(a):
    """--install-prusa-presets / --remove-prusa-presets: EmberCheck print presets in PrusaSlicer (see prusa_presets.py)."""
    import prusa_presets as pp
    manifest = os.path.join(app_dir(), 'prusa_presets_manifest.json')
    msgs = ['--- %s %s %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), VERSION,
                                '--remove-prusa-presets' if a.remove_prusa_presets else '--install-prusa-presets')]
    stats = {}
    def log(m):
        msgs.append(m); eprint(m)
    try:
        if a.remove_prusa_presets:
            pp.remove(a.prusa_dir, manifest, log, backup_dir=os.path.join(app_dir(), 'preset_backups', 'prusaslicer'))
        else:
            if getattr(sys, 'frozen', False):
                line = pp.post_process_line(sys.executable, None, ('--goal {goal} ' + a.pp_args).strip())
            else:
                exe = sys.executable
                w = os.path.join(os.path.dirname(exe), 'pythonw.exe')
                line = pp.post_process_line(w if os.path.exists(w) else exe, os.path.abspath(__file__), ('--goal {goal} ' + a.pp_args).strip())
            bases = [b.strip() for b in a.prusa_base.split(';') if b.strip()] if a.prusa_base else None
            pp.install(line, a.prusa_dir, manifest, log, bases=bases, version=VERSION, stats=stats)
            if pp.prusa_running():
                log('PrusaSlicer is running - restart it to see the new presets.')
    except Exception as ex:
        log('PrusaSlicer preset step failed: %s' % ex)
        stats['status'] = 'error'
    if not a.remove_prusa_presets:
        text = pp.status_text(stats)
        try:   # read by the installer's finish page
            with open(os.path.join(app_dir(), 'prusa_presets_status.txt'), 'w', encoding='utf-8') as f:
                f.write(text + '\n')
        except OSError:
            pass
        if not a.quiet and gui_available():   # Start menu "Add PrusaSlicer presets"
            try:
                import tkinter as tk
                from tkinter import messagebox
                r = tk.Tk(); r.withdraw(); _icon(r)
                (messagebox.showinfo if stats.get('status') == 'ok' else messagebox.showwarning)('EmberCheck', text)
                r.destroy()
            except Exception:
                pass
    try:
        with open(os.path.join(app_dir(), 'presets.log'), 'a', encoding='utf-8') as f:
            f.write('\n'.join(msgs) + '\n')
    except OSError:
        pass
    return 0    # never fail the installer / uninstaller because of presets


def presets_cmd(a):
    import bambu_presets as bp
    manifest = os.path.join(app_dir(), 'presets_manifest.json')
    msgs = ['--- %s %s %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), VERSION,
                                '--remove-presets' if a.remove_presets else '--install-presets')]
    stats = {}
    def log(m):
        msgs.append(m); eprint(m)
    try:
        if a.remove_presets:
            bp.remove(a.bambu_dir, manifest, log)
        else:
            frozen = getattr(sys, 'frozen', False)
            if frozen:
                line = bp.post_process_line(sys.executable, None, ('--goal {goal} ' + a.pp_args).strip())
            else:
                exe = sys.executable
                w = os.path.join(os.path.dirname(exe), 'pythonw.exe')
                line = bp.post_process_line(w if os.path.exists(w) else exe, os.path.abspath(__file__), ('--goal {goal} ' + a.pp_args).strip())
            models = None
            sysdir = bp.system_profiles_dir(a.bambu_dir or bp.bambu_data_dir())
            if a.repoint_only:   # installer, presets task unchecked: keep 1.x presets working after PrintOptimizer.exe is gone
                ch = bp.repoint_all(line, a.bambu_dir, os.path.join(app_dir(), 'preset_backups'), log)
                stats.update(status='ok', repointed=ch, printers=[], written=[], repoint_only=True)
                raise Cancelled()
            if a.printers and sysdir:
                models = bp.resolve_models(a.printers, sysdir)
                log('selected printers: %s' % ', '.join(models))
            elif a.select and sysdir and gui_available():
                avail, pre = printer_choices(bp, a.bambu_dir, sysdir, manifest)
                import ui
                models = ui.choose_printers(avail, pre)
                if models is None:
                    log('printer selection cancelled - presets unchanged')
                    stats['status'] = 'cancelled'
                    raise Cancelled()
            elif sysdir and (bp._load(manifest) or {}).get('models'):   # keep the printers chosen last time
                models = printer_choices(bp, a.bambu_dir, sysdir, manifest)[1]
            bp.install(line, a.bambu_dir, manifest, log, backup_dir=os.path.join(app_dir(), 'preset_backups'), stats=stats,
                       models=models)
            if bp.bambu_running():
                log('Bambu Studio is running - restart it to see the new presets.')
    except Cancelled:
        pass
    except Exception as ex:
        log('preset step failed: %s' % ex)
        stats['status'] = 'error'
    if not a.remove_presets and stats.get('status') != 'cancelled' and not stats.get('repoint_only'):
        text = bp.status_text(stats)
        try:   # read by the installer's finish page
            with open(os.path.join(app_dir(), 'presets_status.txt'), 'w', encoding='utf-8') as f:
                f.write(text + '\n')
        except OSError:
            pass
        if not a.quiet and gui_available():   # Start menu "Add Bambu Studio presets"
            try:
                import tkinter as tk
                from tkinter import messagebox
                r = tk.Tk(); r.withdraw(); _icon(r)
                (messagebox.showinfo if stats.get('status') == 'ok' else messagebox.showwarning)('EmberCheck', text)
                r.destroy()
            except Exception:
                pass
    try:
        with open(os.path.join(app_dir(), 'presets.log'), 'a', encoding='utf-8') as f:
            f.write('\n'.join(msgs) + '\n')
    except OSError:
        pass
    return 0    # never fail the installer / uninstaller because of presets


def sniff_slicer(path):
    """'PrusaSlicer' or 'Bambu Studio' from the first lines of a .gcode file (cheap, for window titles)."""
    try:
        if path and not path.lower().endswith('.3mf'):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                head = f.read(4096)
            if '; generated by PrusaSlicer' in head:
                return 'PrusaSlicer'
    except OSError:
        pass
    return 'Bambu Studio'


def run_job(a, st, src, rpath, stem, ts, log, progress):
    """Process one file. Returns card data dict. Raises Cancelled before anything is written."""
    is3mf = src.lower().endswith('.3mf')
    pp_name = os.environ.get('SLIC3R_PP_OUTPUT_NAME')
    if is3mf:
        outp = a.output or re.sub(r'(\.gcode)?\.3mf$', '', src, flags=re.I) + '.optimized.gcode.3mf'
        zin = zipfile.ZipFile(src)
        names = [n for n in zin.namelist() if re.match(r'Metadata/plate_\d+\.gcode$', n)]
        if not names:
            raise UnsupportedGcode('no Metadata/plate_N.gcode inside - export with "Export plate sliced file"')
        newdata = {}; card = None; receipts = []
        for n in names:
            txt = zin.read(n).decode('utf-8', errors='surrogateescape')
            log('processing %s :: %s' % (src, n))
            new, html, summ = already_stamped(txt, st, n, log) or process_text(txt, st, '%s :: %s' % (os.path.basename(src), n), log, progress)
            rp = rpath if len(names) == 1 else rpath.replace('.html', '_%s.html' % os.path.basename(n).split('.')[0])
            with open(rp, 'w', encoding='utf-8') as f:
                f.write(html)
            log('%s: %s  time %+.1f%%  hot %d->%d  cold %d->%d  errors=%s' % (n, 'OK' if new else 'NOT CHANGED', summ['dt_pct'], summ['hot_before'], summ['hot_after'], summ['cold_before'], summ['cold_after'], summ['errors']))
            if new and not a.dry_run and summ.get('n_edits'):
                newdata[n] = new.encode('utf-8', errors='surrogateescape')
            card = card_data(summ, '%s :: %s' % (os.path.basename(src), n), rp, a.dry_run)
            if n in newdata: receipts.append(('%s :: %s -> %s' % (src, n, outp), card))
        progress('write', 0.0)
        if newdata:
            with zipfile.ZipFile(outp, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    base = item.filename
                    if base in newdata:
                        data = newdata[base]
                    elif base.endswith('.gcode.md5') and base[:-4] in newdata:
                        data = hashlib.md5(newdata[base[:-4]]).hexdigest().upper().encode()
                    zout.writestr(item, data)
            log('wrote %s' % outp)
            for r in receipts: log_run(*r)
        progress.cancel_flag = None
        progress('write', 1.0)
        return card
    with open(src, 'r', encoding='utf-8', errors='surrogateescape', newline='') as f:
        txt = f.read()
    log('processing %s (pp_name=%s)' % (src, pp_name))
    new, html, summ = already_stamped(txt, st, src, log) or process_text(txt, st, pp_name or os.path.basename(src), log, progress)
    with open(rpath, 'w', encoding='utf-8') as f:
        f.write(html)
    log('result: %s  model time %+.1f%%  hot %d->%d  cold %d->%d  errors=%s  (%.1fs)' % (
        'OK' if new else 'NOT CHANGED', summ['dt_pct'], summ['hot_before'], summ['hot_after'], summ['cold_before'], summ['cold_after'], summ['errors'], summ['seconds']))
    progress('write', 0.0)   # last chance to cancel - nothing has been written yet
    if new is not None and not a.dry_run and summ.get('n_edits'):
        if a.keep_original:
            shutil.copyfile(src, os.path.join(os.path.dirname(rpath), '%s_%s_original.gcode' % (stem, ts)))
        outp = a.output or src
        tmp = outp + '.po_tmp'
        with open(tmp, 'w', encoding='utf-8', errors='surrogateescape', newline='') as f:
            f.write(new)
        os.replace(tmp, outp)
        log('wrote %s' % outp)
    progress.cancel_flag = None  # written: cancelling is no longer possible
    progress('write', 1.0)
    slicer = summ.get('slicer') or sniff_slicer(src)
    # PrusaSlicer: SLIC3R_PP_OUTPUT_NAME is the final export path, so the card shows the real file name
    shown = (os.path.basename(pp_name.replace('\\', '/')) if slicer == 'PrusaSlicer' else '%s slice' % slicer) if pp_name else os.path.basename(src)
    card = card_data(summ, shown, rpath, a.dry_run)
    card['slicer'] = slicer
    # Bambu Studio waits for the card ("Continue to Print"); PrusaSlicer has already finished exporting
    card['from_bambu'] = bool(pp_name) and slicer == 'Bambu Studio'
    if new is not None and not a.dry_run and summ.get('n_edits'):
        log_run('%s%s' % (a.output or src, (' (%s: %s)' % (slicer, pp_name)) if pp_name else ''), card)
    return card


def main(argv=None):
    ap = argparse.ArgumentParser(description='EmberCheck ' + VERSION + ' - print optimizer for Bambu Studio and PrusaSlicer')
    ap.add_argument('input', nargs='?', help='G-code (.gcode) or sliced project (.gcode.3mf / .3mf)')
    ap.add_argument('-o', '--output', help='output file (default: in place for .gcode, *.optimized.gcode.3mf for 3mf)')
    ap.add_argument('--report', help='HTML report path')
    ap.add_argument('--report-dir', help='folder for reports (default Documents/EmberCheck/reports)')
    ap.add_argument('--dry-run', action='store_true', help='analyse + report only, do not change the G-code')
    ap.add_argument('--goal', choices=['quality', 'balanced', 'speed'], default='balanced')
    ap.add_argument('--max-speedup', type=float, help='cap on speed increase (default 1.0/1.25/1.5 by goal)')
    ap.add_argument('--material', help='override filament type (PLA, PETG, ABS, ASA, TPU, PC, PA)')
    ap.add_argument('--chamber', type=float, help='chamber/ambient temperature in C (default: config or 35 for enclosed)')
    ap.add_argument('--skip-layers', type=int, default=2, help='never change speeds on the first N layers (default 2)')
    ap.add_argument('--no-speed', action='store_true'); ap.add_argument('--no-fan', action='store_true')
    ap.add_argument('--no-overhang', action='store_true'); ap.add_argument('--no-bridge-fan', action='store_true')
    ap.add_argument('--no-accel', action='store_true', help='keep the slicer\'s accelerations (no M204 changes)')
    ap.add_argument('--no-reorder', action='store_true', help='keep the slicer\'s infill island order')
    ap.add_argument('--no-hop-skip', action='store_true', help='keep every Z-hop and retraction')
    ap.add_argument('--arcs', choices=['auto', 'on', 'off'], default='auto', help='arc fitting (auto: off on printers with firmware curve planning)')
    ap.add_argument('--no-time-limit', action='store_true', help='let speed/balanced add time (old behaviour)')
    ap.add_argument('--reorder', action='store_true', help='re-order infill islands to shorten travel')
    ap.add_argument('--fix-strings', action='store_true', help='add retraction to un-retracted open-air travels')
    ap.add_argument('--no-m73', action='store_true', help='do not update M73 remaining-time values')
    ap.add_argument('--open', action='store_true', help='open the full HTML report in the browser when done')
    ap.add_argument('--no-gui', action='store_true', help='no progress window / results card')
    ap.add_argument('--keep-original', action='store_true', help='save a copy of the original G-code next to the report')
    ap.add_argument('--strict', action='store_true', help='return an error code on failure (Bambu Studio will then show an error)')
    ap.add_argument('--show-summary', help=argparse.SUPPRESS)
    ap.add_argument('--auto-close', type=int, default=60, help='seconds before the results card closes itself (0 = never)')
    ap.add_argument('--pos', help=argparse.SUPPRESS)
    ap.add_argument('--install-presets', action='store_true', help='create "<layer>mm <printer> EmberCheck <Goal>" presets in Bambu Studio')
    ap.add_argument('--printers', default='', help='with --install-presets: printers to create presets for, e.g. "X1C;P1S;A1 mini" '
                    '(default: the printers set up in Bambu Studio)')
    ap.add_argument('--select', action='store_true', help='with --install-presets: show the printer selection window')
    ap.add_argument('--repoint-only', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--list-printers', metavar='FILE', help=argparse.SUPPRESS)
    ap.add_argument('--check-stamp', metavar='GCODE', help='check the EmberCheck stamp of an optimized .gcode / .gcode.3mf (body SHA-256)')
    ap.add_argument('--remove-presets', action='store_true', help='remove the presets created by --install-presets')
    ap.add_argument('--install-prusa-presets', action='store_true',
                    help='create "<print profile> - EmberCheck <Goal>" print presets in PrusaSlicer (based on the selected print profile)')
    ap.add_argument('--prusa-base', default='', help='with --install-prusa-presets: base print profile(s), e.g. "0.20 mm NORMAL (0.4 mm nozzle) @CREALITY"')
    ap.add_argument('--remove-prusa-presets', action='store_true', help='remove the presets created by --install-prusa-presets')
    ap.add_argument('--prusa-dir', help=argparse.SUPPRESS)
    ap.add_argument('--pp-args', default='', help='extra arguments added to the presets\' post-processing line (each preset already has its own --goal)')
    ap.add_argument('--bambu-dir', help=argparse.SUPPRESS)
    ap.add_argument('--quiet', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--open-reports', action='store_true', help='open the reports folder')
    ap.add_argument('--self-test', action='store_true', help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.self_test:   # used by CI on the frozen exe: every optional module must be importable
        problems = []
        if not HAVE_GEOM:
            problems.append('geometry: %s' % GEOM_ERROR)
        for mod in ('tkinter', 'ui', 'bambu_presets', 'prusa_presets', 'report', 'project_info', 'stamp'):
            try:
                __import__(mod)
            except Exception as ex:
                problems.append('%s: %s' % (mod, ex))
        msg = 'self-test %s %s' % ('FAILED' if problems else 'OK', '; '.join(problems))
        eprint(msg)
        if a.report:
            with open(a.report, 'w', encoding='utf-8') as f:
                f.write(msg + '\n')
        return 1 if problems else 0
    if a.list_printers:
        return list_printers(a)
    if a.check_stamp:
        import stamp
        ok, msg = stamp.check_file(a.check_stamp)
        if sys.stdout is not None:
            print(msg)
        if getattr(sys, 'frozen', False) and gui_available() and not a.no_gui:   # windowed exe has no console
            try:
                import tkinter as tk
                from tkinter import messagebox
                r = tk.Tk(); r.withdraw(); _icon(r); (messagebox.showinfo if ok else messagebox.showwarning)('EmberCheck', msg); r.destroy()
            except Exception:
                pass
        return 0 if ok else 1
    if a.install_presets or a.remove_presets:
        return presets_cmd(a)
    if a.install_prusa_presets or a.remove_prusa_presets:
        return prusa_presets_cmd(a)
    if a.open_reports:
        d = a.report_dir or default_report_dir(); os.makedirs(d, exist_ok=True)
        _open_path(d)
        return 0

    if a.show_summary:   # detached child process: just show the card
        import ui
        pos = tuple(int(v) for v in a.pos.split(',')) if a.pos else None
        ui.show_summary(a.show_summary, auto_close=a.auto_close, pos=pos)
        return 0
    if not a.input:
        a.input = pick_file() if (not a.no_gui and gui_available()) else None
        if not a.input:
            if a.no_gui or not gui_available():
                ap.error('input file required')
            return 0
        a.open = True   # started from the Start menu: show the full report at the end

    pp_name = os.environ.get('SLIC3R_PP_OUTPUT_NAME')
    src = a.input
    is3mf = src.lower().endswith('.3mf')
    stem = os.path.basename(pp_name or src)
    for ext in ('.gcode.3mf', '.3mf', '.gcode'):
        if stem.lower().endswith(ext): stem = stem[:-len(ext)]; break
    slicer = sniff_slicer(src)
    if stem.startswith('.') or not stem.strip('.'):
        stem = 'bambu_slice' if slicer == 'Bambu Studio' else 'prusaslicer_slice'   # hidden temp file (e.g. .12345.0.gcode)
    rdir = a.report_dir or (os.path.dirname(os.path.abspath(a.output)) if a.output else
                            (default_report_dir() if (pp_name or not is3mf) and not a.report else os.path.dirname(os.path.abspath(src))))
    os.makedirs(rdir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    rpath = a.report or os.path.join(rdir, '%s_%s_report.html' % (stem, ts))
    logpath = os.path.join(os.path.dirname(os.path.abspath(rpath)), 'optimizer.log')

    def log(msg):
        line = '[%s] %s' % (datetime.datetime.now().strftime('%H:%M:%S'), msg)
        eprint(line)
        try:
            with open(logpath, 'a', encoding='utf-8') as f: f.write(line + '\n')
        except OSError: pass

    st = Settings(goal=a.goal, max_speedup=a.max_speedup, material=a.material, chamber=a.chamber,
                  skip_layers=a.skip_layers, speed=not a.no_speed, fan=not a.no_fan, overhang=not a.no_overhang,
                  bridge_fan=not a.no_bridge_fan, reorder=True if a.reorder else (False if a.no_reorder else None),
                  hops='none' if a.no_hop_skip else None, arcs=a.arcs, fix_strings=a.fix_strings, m73=not a.no_m73,
                  accel=not a.no_accel, time_budget='none' if a.no_time_limit else 'goal')
    st.dry_run = a.dry_run
    if not HAVE_GEOM:
        log('WARNING: shapely/numpy not available (%s) - island, overhang and travel analysis disabled (pip install shapely)' % GEOM_ERROR)
    use_gui = not a.no_gui and gui_available()
    card = None; err = None; cancelled = False; pos = None
    try:
        if use_gui:
            import ui
            title = ('%s slice' % slicer) if pp_name else os.path.basename(src)
            def work(cb, cancel_flag):
                return run_job(a, st, src, rpath, stem, ts, log, Progress(cb, cancel_flag))
            card, err, cancelled, pos = ui.ProgressWindow(title, slicer).run(work)
            if isinstance(err, Cancelled):
                cancelled = True; err = None
        else:
            card = run_job(a, st, src, rpath, stem, ts, log, Progress())
    except Cancelled:
        cancelled = True
    except Exception as ex:
        err = ex
    if cancelled:
        log('cancelled by user - G-code left unchanged')
        return 0
    if err is not None:
        log('FAILED, G-code left unchanged: %s\n%s' % (err, ''.join(traceback.format_exception(type(err), err, err.__traceback__))))
        card = {'status': 'failed', 'name': ('%s slice' % slicer) if pp_name else os.path.basename(src), 'errors': [str(err)], 'report': None,
                'recommendations': [['Log', 'Details are in optimizer.log in ' + os.path.dirname(logpath)]]}
    if card is not None:
        card['log_dir'] = os.path.dirname(logpath)
    if card and card.get('report'):
        eprint('report: ' + card['report'])
    if use_gui and card:
        try:
            jp = os.path.join(os.path.dirname(logpath), '%s_%s_summary.json' % (stem, ts))
            with open(jp, 'w', encoding='utf-8') as f:
                json.dump(card, f, indent=1)
            spawn_summary(jp, pos, a.auto_close)
        except Exception as ex:
            log('could not show results card: %s' % ex)
    if a.open and card and card.get('report'):
        try:
            if sys.platform == 'win32':
                os.startfile(card['report'])  # noqa
            else:
                webbrowser.open('file://' + os.path.abspath(card['report']))
        except Exception:
            pass
    return 1 if (err is not None and a.strict) else 0


if __name__ == '__main__':
    sys.exit(main())
