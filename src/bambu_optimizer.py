#!/usr/bin/env python3
"""Bambu Print Optimizer - free, local, Helio-style thermal check + speed/fan/travel optimiser.

Bambu Studio post-processing usage (Process > Others > Post-processing scripts):
    "C:\\Path\\To\\python.exe" "C:\\Path\\To\\bambu_optimizer.py" --goal balanced
Bambu Studio appends the temporary G-code path as the last argument; the file is edited in place.

Standalone:
    python bambu_optimizer.py model.gcode -o model.opt.gcode
    python bambu_optimizer.py plate.gcode.3mf            (writes plate.optimized.gcode.3mf)
    python bambu_optimizer.py model.gcode --dry-run --open   (report only)
"""
import argparse, os, sys, time, datetime, hashlib, io, zipfile, re, traceback, webbrowser, shutil, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gcode_model import GcodeFile, Kinematics, estimate_times, UnsupportedGcode  # noqa: E402
from optimizer import Optimizer, Settings, HAVE_GEOM, GEOM_ERROR  # noqa: E402
from emitter import emit, validate, rewrite_m73  # noqa: E402
import report as R  # noqa: E402
from progress import Progress, Cancelled, noop  # noqa: E402

VERSION = '1.2.1'


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


def default_report_dir():
    home = os.path.expanduser('~')
    docs = windows_documents_dir() if sys.platform == 'win32' else None
    if not docs:
        docs = os.path.join(home, 'Documents')
    return os.path.join(docs if os.path.isdir(docs) else home, 'BambuPrintOptimizer', 'reports')


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
    out, est = emit(opt, progress=progress)
    m73n = 0
    if st.m73:
        out, m73n = rewrite_m73(g, out, opt.kin, progress=progress)
    errs, metrics = validate(g, out, opt, progress=progress)
    ng = GcodeFile(out) if not errs else None
    kin = Kinematics(g)
    tb = body_time(g, kin); ta = body_time(ng, kin) if ng else tb
    bt = None
    for ln in g.raw_lines[:30]:
        mm = re.search(r'model printing time:\s*([^;]+)', ln)
        if mm: bt = mm.group(1).strip(); break
    hi = opt.mat['t_high']
    hot_b = sum(1 for e in opt.base if e.Tmax is not None and e.Tmax > hi)
    hot_a = sum(1 for e in opt.opt if e.Tmax is not None and e.Tmax > hi)
    cold_b = sum(1 for e in opt.base if e.cold_frac >= 0.25)
    cold_a = sum(1 for e in opt.opt if e.cold_frac >= 0.25)
    need = [opt.opt[i].time for i in range(opt.nl) if opt.base[i].Tmax is not None and opt.base[i].Tmax > hi]
    cat, flow_lim, ext_t = R.time_breakdown(opt)
    dec = opt.decisions
    sped = sum(1 for d in dec if d.startswith('speed') or (d.startswith('cold->s') and not d.startswith('cold->s1.00')))
    slowed = sum(1 for d in dec if d.startswith('hot->s') and not d.startswith('hot->s1.00')) + dec.count('hot-residual')
    fanl = sum(1 for d in dec if 'fan' in d) + dec.count('hot-residual')
    changes = [
        '%d layers sped up (inner walls / infill only, max %.2fx, flow-limited to %g mm&sup3;/s)' % (sped, st.max_speedup, opt.max_vol),
        '%d layers slowed for cooling, %d layers with fan adjusted' % (slowed, fanl),
        '%d feedrate values changed, %d existing fan commands changed, %d fan commands inserted (overhang/bridge boost + restore)' % (
            est['f_changed'], est['fan_changed'], est['fan_inserted']),
        '%d wall segments slowed for overhangs not marked by the slicer' % len(opt.ovf),
        '%d anti-string retractions added' % opt.travel['fixed'],
        '%d infill runs re-ordered' % (len(opt.order) and opt.reorder_stats['reordered_runs'] if st.reorder else 0),
        '%d M73 remaining-time values updated' % m73n,
        'Nothing else touched: no temperatures, no E values, no start/end/AMS/timelapse G-code.']
    summary = {'t_before': tb, 't_after': ta, 'dt_pct': 100 * (ta - tb) / tb if tb else 0, 'bambu_time': bt,
               'hot_before': hot_b, 'hot_after': hot_a, 'cold_before': cold_b, 'cold_after': cold_a,
               'hot_layer_time_needed': int(max(need) + 0.999) if need else None, 'breakdown': cat,
               'flow_limited_share': flow_lim / ext_t if ext_t else 0,
               'accel_share': cat['Extrusion accel/decel loss'] / ext_t if ext_t else 0,
               'changes': changes, 'errors': errs, 'metrics': metrics, 'seconds': time.time() - t0,
               'travel': opt.travel, 'reorder': opt.reorder_stats, 'ov': getattr(opt, 'ov_stats', {}),
               'material': opt.mat_name, 'layers': opt.nl, 'est': est}
    applied = (not errs) and not st.dry_run
    desc = 'goal=%s, max speed-up %.2fx, %s%s%s' % (st.goal, st.max_speedup, 'reorder on, ' if st.reorder else '',
                                                   'fix-strings on, ' if st.fix_strings else '', 'v' + VERSION)
    html = R.build(opt, summary, {'errors': errs, 'metrics': metrics}, applied, name, desc)
    summary['recs'] = R.recommendations(opt, summary)
    summary['overhang_adjusted'] = len(opt.ovf) + len(opt.boost)
    summary['n_edits'] = est['f_changed'] + est['fan_changed'] + est['fan_inserted'] + est['f_inserted'] + est['acc_inserted'] + \
        opt.travel['fixed'] + (1 if opt.order and st.reorder else 0)
    progress('verify', 1.0)
    return (out if not errs else None), html, summary


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
    order = {'Cooling / min layer time': 0, 'Chamber / cold layers': 1, 'Stringing / travel': 2, 'Overhangs': 3, 'Bridges': 4}
    recs = sorted(summ.get('recs') or [], key=lambda r: order.get(r[0], 9))
    return {'status': status, 'name': name, 'dt_pct': summ.get('dt_pct', 0.0), 'bambu_time': summ.get('bambu_time'),
            'hot_before': summ.get('hot_before', 0), 'hot_after': summ.get('hot_after', 0),
            'cold_before': summ.get('cold_before', 0), 'cold_after': summ.get('cold_after', 0),
            'overhang_adjusted': summ.get('overhang_adjusted', 0),
            'open_air': summ.get('travel', {}).get('open_air', 0),
            'open_air_unretracted': summ.get('travel', {}).get('open_air_unretracted', 0),
            'recommendations': [list(r) for r in recs[:3]], 'report': report_path, 'errors': errs,
            'seconds': summ.get('seconds')}


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
        r = tk.Tk(); r.withdraw()
        p = filedialog.askopenfilename(title='Print Optimizer - choose a sliced plate',
                                       filetypes=[('Sliced plate / G-code', '*.3mf *.gcode'), ('All files', '*.*')])
        r.destroy()
        return p or None
    except Exception:
        return None


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
            bp.install(line, a.bambu_dir, manifest, log, backup_dir=os.path.join(app_dir(), 'preset_backups'), stats=stats)
            if bp.bambu_running():
                log('Bambu Studio is running - restart it to see the new presets.')
    except Exception as ex:
        log('preset step failed: %s' % ex)
        stats['status'] = 'error'
    if not a.remove_presets:
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
                r = tk.Tk(); r.withdraw()
                (messagebox.showinfo if stats.get('status') == 'ok' else messagebox.showwarning)('Print Optimizer', text)
                r.destroy()
            except Exception:
                pass
    try:
        with open(os.path.join(app_dir(), 'presets.log'), 'a', encoding='utf-8') as f:
            f.write('\n'.join(msgs) + '\n')
    except OSError:
        pass
    return 0    # never fail the installer / uninstaller because of presets


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
        newdata = {}; card = None
        for n in names:
            txt = zin.read(n).decode('utf-8', errors='surrogateescape')
            log('processing %s :: %s' % (src, n))
            new, html, summ = process_text(txt, st, '%s :: %s' % (os.path.basename(src), n), log, progress)
            rp = rpath if len(names) == 1 else rpath.replace('.html', '_%s.html' % os.path.basename(n).split('.')[0])
            with open(rp, 'w', encoding='utf-8') as f:
                f.write(html)
            log('%s: %s  time %+.1f%%  hot %d->%d  cold %d->%d  errors=%s' % (n, 'OK' if new else 'NOT CHANGED', summ['dt_pct'], summ['hot_before'], summ['hot_after'], summ['cold_before'], summ['cold_after'], summ['errors']))
            if new and not a.dry_run and summ.get('n_edits'):
                newdata[n] = new.encode('utf-8', errors='surrogateescape')
            card = card_data(summ, '%s :: %s' % (os.path.basename(src), n), rp, a.dry_run)
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
        progress.cancel_flag = None
        progress('write', 1.0)
        return card
    with open(src, 'r', encoding='utf-8', errors='surrogateescape', newline='') as f:
        txt = f.read()
    log('processing %s (pp_name=%s)' % (src, pp_name))
    new, html, summ = process_text(txt, st, pp_name or os.path.basename(src), log, progress)
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
    return card_data(summ, pp_name and 'Bambu Studio slice' or os.path.basename(src), rpath, a.dry_run)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Bambu Print Optimizer ' + VERSION)
    ap.add_argument('input', nargs='?', help='G-code (.gcode) or sliced project (.gcode.3mf / .3mf)')
    ap.add_argument('-o', '--output', help='output file (default: in place for .gcode, *.optimized.gcode.3mf for 3mf)')
    ap.add_argument('--report', help='HTML report path')
    ap.add_argument('--report-dir', help='folder for reports (default Documents/BambuPrintOptimizer/reports)')
    ap.add_argument('--dry-run', action='store_true', help='analyse + report only, do not change the G-code')
    ap.add_argument('--goal', choices=['quality', 'balanced', 'speed'], default='balanced')
    ap.add_argument('--max-speedup', type=float, help='cap on speed increase (default 1.0/1.25/1.5 by goal)')
    ap.add_argument('--material', help='override filament type (PLA, PETG, ABS, ASA, TPU, PC, PA)')
    ap.add_argument('--chamber', type=float, help='chamber/ambient temperature in C (default: config or 35 for enclosed)')
    ap.add_argument('--skip-layers', type=int, default=2, help='never change speeds on the first N layers (default 2)')
    ap.add_argument('--no-speed', action='store_true'); ap.add_argument('--no-fan', action='store_true')
    ap.add_argument('--no-overhang', action='store_true'); ap.add_argument('--no-bridge-fan', action='store_true')
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
    ap.add_argument('--install-presets', action='store_true', help='create "<default process> - Optimized" presets in Bambu Studio for your printers')
    ap.add_argument('--remove-presets', action='store_true', help='remove the presets created by --install-presets')
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
        for mod in ('tkinter', 'ui', 'bambu_presets', 'report'):
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
    if a.install_presets or a.remove_presets:
        return presets_cmd(a)
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
    if stem.startswith('.') or not stem.strip('.'):
        stem = 'bambu_slice'   # Bambu Studio passes its hidden temp file (e.g. .12345.0.gcode)
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
                  bridge_fan=not a.no_bridge_fan, reorder=a.reorder, fix_strings=a.fix_strings, m73=not a.no_m73)
    st.dry_run = a.dry_run
    if not HAVE_GEOM:
        log('WARNING: shapely/numpy not available (%s) - island, overhang and travel analysis disabled (pip install shapely)' % GEOM_ERROR)
    use_gui = not a.no_gui and gui_available()
    card = None; err = None; cancelled = False; pos = None
    try:
        if use_gui:
            import ui
            title = 'Bambu Studio slice' if pp_name else os.path.basename(src)
            def work(cb, cancel_flag):
                return run_job(a, st, src, rpath, stem, ts, log, Progress(cb, cancel_flag))
            card, err, cancelled, pos = ui.ProgressWindow(title).run(work)
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
        card = {'status': 'failed', 'name': 'Bambu Studio slice' if pp_name else os.path.basename(src), 'errors': [str(err)], 'report': None,
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
