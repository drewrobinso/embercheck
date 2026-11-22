"""Create / remove "<layer>mm <printer> EmberCheck <Goal>" process presets in Bambu Studio
(e.g. "0.20mm X1C EmberCheck Balanced"), one per selected printer x nozzle x main system layer-height preset x goal.

Used by the Windows installer (EmberCheck.exe --install-presets / --remove-presets) and by hand on Windows, macOS and Linux.
Format follows Bambu Studio's PresetCollection::load_presets (src/libslic3r/Preset.cpp):
  * <data_dir>/user/<user_id or "default">/process/<preset name>.json  (file name == preset name)
  * a parseable "version" is required, "inherits" must name an existing (system) preset
  * <name>.info sidecar holds sync_info / user_id / setting_id / base_id / updated_time
Only presets this tool created (marker key + manifest) are ever removed.
"""
import glob
import json
import os
import re
import sys
import time

SUFFIX = ' - Optimized'                      # 1.0-1.1 naming, migrated away from by install()
MARK = 'Created by EmberCheck'                     # stored in the preset "description"
LEGACY_MARKS = ('Created by Bambu Print Optimizer',)   # 1.1-1.4.0
GOALS = [('balanced', 'Balanced'), ('speed', 'Speed'), ('quality', 'Quality')]   # = embercheck --goal choices
NAME_RE = re.compile(r' EmberCheck (%s)$' % '|'.join(g[1] for g in GOALS))
LEGACY_NAME_RE = re.compile(r' AI (%s)$' % '|'.join(g[1] for g in GOALS))   # 1.2-1.4.0 "... AI <Goal>"
# the 1.x PrintOptimizer.exe (removed by the upgrade)
_OLD_EXE = r'PrintOptimizer\.exe'
OLD_EXE_RE = re.compile(r'"[^"]*%s"|\S*%s' % (_OLD_EXE, _OLD_EXE), re.I)
# Main layer-height presets only (no "High Quality", "Strength", "Speed", ... variants), best first per layer
MAIN_KINDS = ['Standard', 'Optimal', 'Fine', 'Draft', 'Extra Draft']
MAX_LAYERS = 3        # per printer/nozzle: the default layer height and its nearest neighbours
SHORT_MODEL = {'X1 Carbon': 'X1C'}
FALLBACK_MODELS = ['Bambu Lab X1 Carbon', 'Bambu Lab X1', 'Bambu Lab X1E', 'Bambu Lab P1P', 'Bambu Lab P1S', 'Bambu Lab P2S',
                   'Bambu Lab A1 mini', 'Bambu Lab A1', 'Bambu Lab H2D', 'Bambu Lab H2D Pro', 'Bambu Lab H2S', 'Bambu Lab H2C',
                   'Bambu Lab X2D', 'Bambu Lab A2L']   # only used to order models when BBL.json has no machine_model_list


def bambu_data_dir():
    if sys.platform == 'win32':
        return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~\\AppData\\Roaming')), 'BambuStudio')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/BambuStudio')
    return os.path.expanduser('~/.config/BambuStudio')


def _load(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def load_conf(data_dir):
    """BambuStudio.conf = JSON followed by a '# MD5 checksum ...' line (AppConfig::save). Strip '#' lines and
    anything after the last '}'. Returns {} if unreadable. Never log the contents (it holds printer access codes)."""
    try:
        with open(os.path.join(data_dir, 'BambuStudio.conf'), encoding='utf-8', errors='replace') as f:
            txt = f.read()
    except OSError:
        return {}
    txt = '\n'.join(l for l in txt.splitlines() if not l.lstrip().startswith('#'))
    end = txt.rfind('}')
    if end < 0:
        return {}
    try:
        j = json.loads(txt[:end + 1])
        return j if isinstance(j, dict) else {}
    except ValueError:
        return {}


def sync_enabled(conf):
    """app.sync_user_preset: Bambu Studio only syncs user presets with the cloud when this is "true"
    (GUI_App: start_sync_user_preset). Default false."""
    app = conf.get('app') if isinstance(conf.get('app'), dict) else {}
    v = app.get('sync_user_preset', False)
    return v is True or str(v).strip().lower() in ('true', '1')


def system_profile_candidates(data_dir, extra=()):
    """Possible locations of Bambu Studio's vendor profiles (BBL.json + BBL/machine)."""
    cands = [os.path.join(data_dir, 'system')] + list(extra)
    if sys.platform == 'win32':
        for pf in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramW6432', '')):
            if pf:
                cands.append(os.path.join(pf, 'Bambu Studio', 'resources', 'profiles'))
    elif sys.platform == 'darwin':
        for app in ('BambuStudio.app', 'Bambu Studio.app'):
            for root in ('/Applications', os.path.expanduser('~/Applications')):
                cands.append(os.path.join(root, app, 'Contents', 'Resources', 'profiles'))
    return cands


def system_profiles_dir(data_dir, extra=()):
    """Bambu copies the vendor bundle to <data_dir>/system; fall back to the program's resources/profiles."""
    for c in system_profile_candidates(data_dir, extra):
        if os.path.isfile(os.path.join(c, 'BBL.json')) and os.path.isdir(os.path.join(c, 'BBL', 'machine')):
            return c
    return None


def installed_printers(data_dir, sysdir, conf=None):
    """System machine preset names like 'Bambu Lab H2S 0.4 nozzle' the user has in Bambu Studio, from:
    conf "models" (enabled vendor models + nozzle variants), conf presets.machine (selected printer) and other
    presets.* machine entries, and user machine presets (their "inherits", followed through user parents)."""
    conf = load_conf(data_dir) if conf is None else conf
    found = []
    models = conf.get('models') if isinstance(conf.get('models'), list) else []
    for m in models:
        if isinstance(m, dict) and str(m.get('vendor', 'BBL')) == 'BBL' and m.get('model'):
            for nd in re.split(r'[;,]', str(m.get('nozzle_diameter', '0.4'))):
                nd = nd.strip().strip('"').strip()
                if nd:
                    found.append('%s %s nozzle' % (m['model'], nd))
    presets = conf.get('presets') if isinstance(conf.get('presets'), dict) else {}
    for k, v in presets.items():
        if isinstance(v, str) and (k == 'machine' or k.startswith('machine')):
            found.append(v)
    user_machines = {}
    for p in glob.glob(os.path.join(data_dir, 'user', '*', 'machine', '*.json')):
        j = _load(p) or {}
        user_machines[j.get('name') or os.path.basename(p)[:-5]] = j.get('inherits', '')
    for n in list(found) + list(user_machines):
        seen = 0
        while n in user_machines and seen < 10:      # user printer -> its (system) parent
            n = user_machines[n]; seen += 1
        found.append(n)
    out = []
    for n in found:
        if n and n not in out and os.path.isfile(os.path.join(sysdir, 'BBL', 'machine', n + '.json')):
            out.append(n)
    return out


def active_preset_folder(data_dir):
    """Folder Bambu Studio loads user presets from: BambuStudio.conf app.preset_folder (the account id when
    signed in, see PresetBundle::load_user_presets). Empty -> "default"."""
    conf = load_conf(data_dir)
    app = conf.get('app') if isinstance(conf.get('app'), dict) else {}
    for v in (app.get('preset_folder'), conf.get('preset_folder')):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def user_dirs(data_dir):
    """Every existing user/<id> folder (signed-in accounts and "default") + "default" + the active account folder."""
    base = os.path.join(data_dir, 'user')
    names = [os.path.basename(d) for d in glob.glob(os.path.join(base, '*')) if os.path.isdir(d)]
    for extra in ('default', active_preset_folder(data_dir)):
        if extra and extra not in names:
            names.append(extra)
    return [os.path.join(base, n) for n in sorted(names)]


def _references_us(preset):
    pp = preset.get('post_process') if isinstance(preset, dict) else None
    txt = ' '.join(pp) if isinstance(pp, list) else str(pp or '')
    return bool(re.search(r'bambu_optimizer\.py|printoptimizer|embercheck\.exe|embercheck\.py', txt, re.I))


def _is_ours(preset):
    if not isinstance(preset, dict): return False
    desc = str(preset.get('description', ''))
    return MARK in desc or any(m in desc for m in LEGACY_MARKS) or _references_us(preset)


def _read_info(path):
    info = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                if '=' in line:
                    k, v = line.split('=', 1)
                    info[k.strip()] = v.strip()
    except OSError:
        pass
    return info


def _write_info(path, info):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        for k in ('sync_info', 'user_id', 'setting_id', 'base_id', 'updated_time'):
            f.write('%s = %s\n' % (k, info.get(k, '')))


def _touch_info(info):
    """Local change to a preset: newer updated_time; if it is synced to the Bambu cloud (has a setting_id) mark it
    "update" so Bambu Studio uploads the change instead of restoring the old cloud copy."""
    info['updated_time'] = str(int(time.time()))
    if info.get('setting_id') and info.get('sync_info', '') in ('', 'save'):
        info['sync_info'] = 'update'
    return info


def _backup(path, backup_dir, uid):
    if not backup_dir:
        return None
    d = os.path.join(backup_dir, uid); os.makedirs(d, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = None
    for src in (path, path[:-5] + '.info'):
        if os.path.exists(src):
            base = os.path.basename(src)
            dst = os.path.join(d, '%s.%s%s' % (base.rsplit('.', 1)[0], stamp, os.path.splitext(base)[1]))
            with open(src, 'rb') as fi, open(dst, 'wb') as fo:
                fo.write(fi.read())
            out = out or dst
    return out


def post_process_line(exe, script=None, args='--goal balanced'):
    cmd = '"%s"' % exe
    if script:
        cmd += ' "%s"' % script
    return cmd + (' ' + args if args else '')


def bambu_running():
    try:
        import subprocess
        if sys.platform == 'win32':
            out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq bambu-studio.exe', '/NH'], capture_output=True, text=True,
                                 creationflags=0x08000000).stdout
            return 'bambu-studio.exe' in out.lower()
        if sys.platform == 'darwin':
            return subprocess.run(['pgrep', '-x', 'BambuStudio'], capture_output=True).returncode == 0
    except Exception:
        return False
    return False


def available_models(sysdir):
    """[(printer_model, short label, [machine preset names with nozzles])] for every Bambu Lab model in the system
    profiles, in BBL.json machine_model_list order (so new printers appear without code changes)."""
    order = [m.get('name') for m in ((_load(os.path.join(sysdir, 'BBL.json')) or {}).get('machine_model_list') or [])
             if isinstance(m, dict) and m.get('name')] or FALLBACK_MODELS
    by = {}
    for f in glob.glob(os.path.join(sysdir, 'BBL', 'machine', '*.json')):
        j = _load(f) or {}
        n = j.get('name') or os.path.basename(f)[:-5]
        if str(j.get('instantiation', 'true')).lower() != 'true' or not re.search(r' \d\.\d nozzle$', n):
            continue
        pm = j.get('printer_model') or re.sub(r' \d\.\d nozzle$', '', n)
        by.setdefault(pm, []).append(n)
    models = [m for m in order if m in by] + sorted(m for m in by if m not in order)
    return [(m, short_model({'printer_model': m}, m), sorted(by[m], key=lambda x: float(nozzle_of(x)))) for m in models]


def model_of(machine_name, sysdir):
    j = _load(os.path.join(sysdir, 'BBL', 'machine', machine_name + '.json')) or {}
    return j.get('printer_model') or re.sub(r' \d\.\d nozzle$', '', machine_name)


def resolve_models(sel, sysdir):
    """'X1C;P1S;Bambu Lab A1 mini' (short labels or full model names, case-insensitive) -> full model names."""
    avail = available_models(sysdir)
    out = []
    for tok in [t.strip() for t in re.split(r'[;,]', sel or '') if t.strip()]:
        for m, short, _ in avail:
            if tok.lower() in (m.lower(), short.lower(), re.sub(r'^bambu lab ', '', m.lower())):
                if m not in out: out.append(m)
                break
    return out


def short_model(machine_json, machine_name):
    m = machine_json.get('printer_model') or re.sub(r' \d\.\d nozzle$', '', machine_name)
    m = re.sub(r'^Bambu Lab ', '', m).strip()
    return SHORT_MODEL.get(m, m)


def nozzle_of(machine_name):
    mm = re.search(r' (\d\.\d) nozzle$', machine_name)
    return mm.group(1) if mm else '0.4'


def _process_index(sysdir):
    """Instantiable BBL system process presets -> list of (name, json) per compatible printer."""
    idx = {}
    for f in glob.glob(os.path.join(sysdir, 'BBL', 'process', '*.json')):
        j = _load(f) or {}
        if str(j.get('instantiation', 'true')).lower() != 'true' or not j.get('name'):
            continue
        for c in j.get('compatible_printers') or []:
            idx.setdefault(c, []).append((j['name'], j))
    return idx


def plan(data_dir, sysdir, models=None):
    """[(preset name, parent system preset, goal, parent setting_id, machine preset)] for the selected printer models
    (every nozzle the system profiles offer), or, without a selection, for the printers set up in Bambu Studio."""
    idx = _process_index(sysdir)
    out = []
    if models is None:
        machines = installed_printers(data_dir, sysdir)
    else:
        machines = [n for m, _, ns in available_models(sysdir) if m in models for n in ns]
    for m in machines:
        mj = _load(os.path.join(sysdir, 'BBL', 'machine', m + '.json')) or {}
        by_layer = {}
        for name, j in idx.get(m, []):
            mm = re.match(r'^(\d\.\d\d)mm (.+?) @BBL ', name)
            if not mm or mm.group(2) not in MAIN_KINDS:
                continue
            lh = mm.group(1)
            cur = by_layer.get(lh)
            if cur is None or MAIN_KINDS.index(mm.group(2)) < MAIN_KINDS.index(cur[1]):
                by_layer[lh] = (name, mm.group(2), j)
        dp = mj.get('default_print_profile', '')
        dmm = re.match(r'^(\d\.\d\d)mm', dp)
        if not by_layer and dp:     # printer without the usual naming: fall back to its default process
            j = (_load(os.path.join(sysdir, 'BBL', 'process', dp + '.json')) or {})
            if dmm and j:
                by_layer[dmm.group(1)] = (dp, '', j)
        if not by_layer:
            continue
        ref = float(dmm.group(1)) if dmm else 0.20
        layers = sorted(by_layer, key=lambda lh: (abs(float(lh) - ref), float(lh)))[:MAX_LAYERS]
        noz = nozzle_of(m)
        label = short_model(mj, m) + ('' if noz == '0.4' else ' ' + noz)
        for lh in sorted(layers, key=float):
            parent, _, pj = by_layer[lh]
            for goal, gl in GOALS:
                n = '%smm %s EmberCheck %s' % (lh, label, gl)
                if all(x[0] != n for x in out):
                    out.append((n, parent, goal, pj.get('setting_id', ''), m))
    return out


def _owned(path, j):
    base = os.path.basename(path)[:-5]
    return (base.endswith(SUFFIX) or NAME_RE.search(base) or LEGACY_NAME_RE.search(base)) and _is_ours(j)


def _neutralize(path, j, info, note):
    j = dict(j)
    j['post_process'] = []
    j['description'] = note
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(j, f, indent=4)
    _write_info(path[:-5] + '.info', _touch_info(info))


def _retire(path, log, backup_dir, note, synced_folder):
    """Remove one of our presets. Bambu Studio has no file-level "deleted" marker: cloud deletions are only queued
    in memory by its own Delete command (GUI_App::delete_preset_from_cloud), and a cloud preset that is missing
    locally is downloaded again on the next sync. So:
      * cloud sync off for this folder (app.sync_user_preset false, or the offline "default" folder), or the preset
        never got a cloud id: delete the files
      * synced: keep the file, clear post_process (+ note), mark it for upload -> harmless; delete it in Bambu."""
    j = _load(path)
    ipath = path[:-5] + '.info'
    info = _read_info(ipath)
    uid = os.path.basename(os.path.dirname(os.path.dirname(path)))
    if backup_dir:
        _backup(path, backup_dir, uid)
    if synced_folder and info.get('setting_id'):
        _neutralize(path, j, info, note)
        log('cleared cloud-synced preset (delete it in Bambu Studio): %s' % path)
        return 'cleared'
    for q in (path, ipath):
        try:
            os.remove(q)
        except OSError:
            pass
    log('removed preset: %s' % path)
    return 'removed'


def _folder_synced(ud, sync_on):
    return sync_on and os.path.basename(ud) != 'default'


def _exe_of(cmdline):
    mm = re.match(r'\s*"([^"]+\.exe)"', cmdline or '')
    return mm.group(1) if mm and not re.search(r'python[w]?\.exe$', mm.group(1), re.I) else None


def repoint_line(line, new_exe):
    """Point a post-processing line that calls the 1.x PrintOptimizer.exe at the new EmberCheck.exe (arguments kept)."""
    return OLD_EXE_RE.sub(lambda m: '"%s"' % new_exe, line, count=1)


def repoint(cmdline, user_dir, backup_dir=None, log=print, skip=()):
    """Process presets in one user folder whose post-processing calls the 1.x PrintOptimizer.exe (deleted by the
    upgrade): point them at the exe in cmdline, arguments kept. Returns the changed files."""
    new_exe = _exe_of(cmdline); out = []
    if not new_exe:
        return out
    uid = os.path.basename(user_dir)
    for q in sorted(glob.glob(os.path.join(user_dir, 'process', '*.json'))):
        if q in skip: continue
        j = _load(q)
        pp = j.get('post_process') if isinstance(j, dict) else None
        if not isinstance(pp, list) or not any(OLD_EXE_RE.search(str(x)) for x in pp):
            continue
        if backup_dir: _backup(q, backup_dir, uid)
        j = dict(j); j['post_process'] = [repoint_line(str(x), new_exe) for x in pp]
        with open(q, 'w', encoding='utf-8') as f:
            json.dump(j, f, indent=4)
        qi = q[:-5] + '.info'
        if os.path.exists(qi): _write_info(qi, _touch_info(_read_info(qi)))
        out.append(q)
        log('post-processing path updated to EmberCheck.exe: %s' % q)
    return out


def repoint_all(cmdline, data_dir=None, backup_dir=None, log=print):
    return [q for ud in user_dirs(data_dir or bambu_data_dir()) for q in repoint(cmdline, ud, backup_dir, log)]


def install(cmdline, data_dir=None, manifest=None, log=print, sysdir_extra=(), backup_dir=None, stats=None, models=None):
    """cmdline: post-processing line containing '{goal}', e.g. '"C:\\...\\EmberCheck.exe" --goal {goal}'.
    models: printer models to create presets for (full names, see resolve_models); None = the printers set up in
    Bambu Studio. Our presets for printers that are no longer selected are retired.
    stats (dict, optional) is filled with printers / written / removed / cleared / skipped / migrated / repointed / status."""
    st = stats if stats is not None else {}
    st.update(printers=[], written=[], removed=[], cleared=[], skipped=[], migrated=[], repointed=[], pruned=[], status='')
    data_dir = data_dir or bambu_data_dir()
    sysdir = system_profiles_dir(data_dir, sysdir_extra)
    if not sysdir:
        st['status'] = 'nosystem'
        log('Bambu Studio system profiles not found under %s - start Bambu Studio once, then run --install-presets again' % data_dir)
        return []
    conf = load_conf(data_dir)
    if not conf:
        log('BambuStudio.conf not found or unreadable in %s' % data_dir)
    sync_on = sync_enabled(conf)
    log('Bambu cloud sync of user presets: %s' % ('on' if sync_on else 'off'))
    version = (_load(os.path.join(sysdir, 'BBL.json')) or {}).get('version', '01.00.00.00')
    if models is None:
        st['printers'] = installed_printers(data_dir, sysdir, conf)
    else:
        st['printers'] = [n for m, _, ns in available_models(sysdir) if m in models for n in ns]
    if not st['printers']:
        st['status'] = 'noprinter'
        log('no Bambu Lab printers selected or found in BambuStudio.conf / user machine presets - nothing to do')
        return []
    log('printers: %s' % ', '.join(st['printers']))
    todo = plan(data_dir, sysdir, models)
    names = set(t[0] for t in todo)
    written = st['written']
    for ud in user_dirs(data_dir):
        pdir = os.path.join(ud, 'process'); os.makedirs(pdir, exist_ok=True)
        uid = os.path.basename(ud)
        synced = _folder_synced(ud, sync_on)
        legacy = {}     # EmberCheck name -> settings of the 1.2-1.4.0 "AI" preset it replaces (user tweaks carried over)
        # 1) retire 1.0/1.1 "... - Optimized", and 1.2-1.4.0 "... AI <Goal>" presets that belong to us
        for old in sorted(glob.glob(os.path.join(pdir, '*.json'))):
            base = os.path.basename(old)[:-5]
            j = _load(old)
            if not (base.endswith(SUFFIX) or LEGACY_NAME_RE.search(base)) or not _is_ours(j):
                continue
            if LEGACY_NAME_RE.search(base):
                legacy[LEGACY_NAME_RE.sub(lambda m: ' EmberCheck ' + m.group(1), base)] = j
            r = _retire(old, log, backup_dir, 'Replaced by EmberCheck presets named "<layer>mm <printer> EmberCheck <Goal>" '
                        '(e.g. "0.20mm H2S EmberCheck Balanced"). This preset no longer post-processes - delete it in Bambu Studio.', synced)
            st[r].append(old)
        # 2) retire our EmberCheck presets for printers that are no longer selected
        for old in sorted(glob.glob(os.path.join(pdir, '*.json'))):
            base = os.path.basename(old)[:-5]
            if NAME_RE.search(base) and base not in names and _is_ours(_load(old)):
                r = _retire(old, log, backup_dir, 'This printer is no longer selected in EmberCheck; this preset no longer '
                            'post-processes - delete it in Bambu Studio.', synced)
                st['pruned'].append(old); st[r].append(old)
        # 3) write the new set
        for name, parent, goal, base_id, machine in todo:
            path = os.path.join(pdir, name + '.json')
            ipath = os.path.join(pdir, name + '.info')
            exists = os.path.exists(path)
            old = _load(path) if exists else None
            if exists and not _is_ours(old):
                st['skipped'].append(path)
                log('skip %s: a preset with that name already exists and was not created by this tool' % path)
                continue
            line = cmdline.replace('{goal}', goal)
            if exists:      # our own preset from an earlier install: keep the user's tweaks and the cloud id
                preset = dict(old)
                info = _read_info(ipath)
            elif name in legacy:   # carry the user's tweaks over from the old "AI" preset (new name = new cloud entry)
                preset = {k: v for k, v in legacy[name].items() if k not in ('setting_id', 'print_settings_id')}
                info = {'sync_info': '', 'user_id': '' if uid == 'default' else uid, 'setting_id': '', 'base_id': base_id}
                st['migrated'].append(path)
            else:
                preset = {'type': 'process', 'from': 'User', 'is_custom_defined': '0', 'version': version}
                info = {'sync_info': '', 'user_id': '' if uid == 'default' else uid, 'setting_id': '', 'base_id': base_id}
            preset.update({'name': name, 'print_settings_id': name, 'inherits': parent, 'post_process': [line],
                           'compatible_printers': [machine],
                           'description': MARK + '. Runs EmberCheck (--goal %s) after slicing.' % goal})
            preset.setdefault('version', version)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(preset, f, indent=4)
            _write_info(ipath, _touch_info(info))
            written.append(path)
            log('wrote preset: %s' % path)
        # 4) the user's own presets that call PrintOptimizer.exe (removed by this upgrade) -> EmberCheck.exe
        st['repointed'] += repoint(cmdline, ud, backup_dir, log, skip=written)
    st['status'] = 'ok'
    st['names'] = [t[0] for t in todo]
    st['models'] = sorted(set(re.sub(r' \d\.\d nozzle$', '', model_of(t[4], sysdir)) for t in todo))
    if manifest:
        prev = (_load(manifest) or {}).get('presets', [])
        with open(manifest, 'w', encoding='utf-8') as f:
            json.dump({'presets': sorted(set(prev) | set(written)), 'cmdline': cmdline,
                       'models': models if models is not None else None}, f, indent=1)
    return written


def status_text(st):
    """One short paragraph for the installer's finish page / message box."""
    s = st.get('status')
    if s == 'noprinter':
        return ('No Bambu Lab printer was selected or found in Bambu Studio, so no EmberCheck presets were added. Run Start menu > '
                'EmberCheck > "Add Bambu Studio presets" and pick your printers.')
    if s == 'nosystem':
        return ('Bambu Studio\'s printer profiles were not found, so no EmberCheck presets were added. Start Bambu Studio once, '
                'close it, then run Start menu > EmberCheck > "Add Bambu Studio presets".')
    if s != 'ok':
        return 'The Bambu Studio presets could not be added (see presets.log in the install folder).'
    names = st.get('names') or []
    models = [short_model({'printer_model': m}, m) for m in st.get('models') or []]
    eg = next((n for n in names if n.startswith('0.20mm') and n.endswith('Balanced')), names[0] if names else '')
    out = 'Added %d EmberCheck presets for %s, e.g. "%s".' % (len(names), ', '.join(models) or 'your printers', eg)
    if st.get('migrated'):
        out += ' Settings of the old "AI" presets (including your changes) were carried over.'
    old = [p for p in st.get('removed', []) + st.get('cleared', []) if p not in st.get('pruned', [])]
    if old:
        out += ' %d old "AI" / "- Optimized" preset(s) were replaced.' % len(old)
    if st.get('cleared'):
        out += (' %d preset(s) synced to your Bambu account were switched off - delete them in Bambu Studio.' % len(st['cleared']))
    if st.get('pruned'):
        out += ' EmberCheck presets of printers you unchecked were removed (%d file(s)).' % len(st['pruned'])
    if st.get('repointed'):
        out += ' %d of your own preset(s) now call EmberCheck.exe instead of PrintOptimizer.exe.' % len(st['repointed'])
    if st.get('skipped'):
        out += ' %d preset name(s) were already used by your own presets and were left alone.' % len(st['skipped'])
    return out + ' Restart Bambu Studio to see them.'


def remove(data_dir=None, manifest=None, log=print, backup_dir=None):
    """Undo install() in every user/<id> folder: our "... EmberCheck <Goal>", "... AI <Goal>" and "... - Optimized" presets only.
    Deleted, except cloud-synced ones (sync on + cloud id), which are cleared (see _retire) because Bambu Studio
    would re-download a locally deleted cloud preset - still calling the removed exe, so slicing would fail."""
    data_dir = data_dir or bambu_data_dir()
    sync_on = sync_enabled(load_conf(data_dir))
    cands = set((_load(manifest) or {}).get('presets', [])) if manifest else set()
    for ud in user_dirs(data_dir):
        cands |= set(glob.glob(os.path.join(ud, 'process', '*.json')))
    done = []
    for p in sorted(cands):
        j = _load(p)
        if j is None or not _owned(p, j):
            continue     # never touch unrelated presets
        ud = os.path.dirname(os.path.dirname(p))
        _retire(p, log, None, 'EmberCheck was uninstalled; this preset no longer post-processes. Delete it in Bambu Studio.',
                _folder_synced(ud, sync_on))
        done.append(p)
    return done
