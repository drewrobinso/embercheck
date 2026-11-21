"""Create / remove "<layer>mm <printer> AI <Goal>" process presets in Bambu Studio
(e.g. "0.20mm H2S AI Balanced"), one per main system layer-height preset x optimizer goal.

Used by the Windows installer (PrintOptimizer.exe --install-presets / --remove-presets) and usable by hand.
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
MARK = 'Created by Bambu Print Optimizer'   # stored in the preset "description"
GOALS = [('balanced', 'Balanced'), ('speed', 'Speed'), ('quality', 'Quality')]   # = bambu_optimizer --goal choices
NAME_RE = re.compile(r' AI (%s)$' % '|'.join(g[1] for g in GOALS))
# Main layer-height presets only (no "High Quality", "Strength", "Speed", ... variants), best first per layer
MAIN_KINDS = ['Standard', 'Optimal', 'Fine', 'Draft', 'Extra Draft']
MAX_LAYERS = 3        # per printer/nozzle: the default layer height and its nearest neighbours
SHORT_MODEL = {'X1 Carbon': 'X1C'}


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


def system_profiles_dir(data_dir, extra=()):
    """Bambu copies the vendor bundle to <data_dir>/system; fall back to the program's resources/profiles."""
    cands = [os.path.join(data_dir, 'system')] + list(extra)
    if sys.platform == 'win32':
        for pf in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramW6432', '')):
            if pf:
                cands.append(os.path.join(pf, 'Bambu Studio', 'resources', 'profiles'))
    for c in cands:
        if os.path.isfile(os.path.join(c, 'BBL.json')) and os.path.isdir(os.path.join(c, 'BBL', 'machine')):
            return c
    return None


def installed_printers(data_dir, sysdir):
    """Machine preset names like 'Bambu Lab H2S 0.4 nozzle' the user has added in Bambu Studio."""
    found = []
    conf = _load(os.path.join(data_dir, 'BambuStudio.conf')) or {}
    # newer versions: "models": [{"model": "Bambu Lab H2S", "nozzle_diameter": "0.4;0.2", "vendor": "BBL"}]
    for m in conf.get('models', []) if isinstance(conf.get('models'), list) else []:
        if isinstance(m, dict) and m.get('vendor', 'BBL') == 'BBL' and m.get('model'):
            for nd in re.split(r'[;,]', str(m.get('nozzle_diameter', '0.4'))):
                if nd.strip():
                    found.append('%s %s nozzle' % (m['model'], nd.strip()))
    sel = (conf.get('presets') or {}).get('machine')
    if isinstance(sel, str):
        found.append(sel)
    # user machine presets that inherit a system printer
    for p in glob.glob(os.path.join(data_dir, 'user', '*', 'machine', '*.json')):
        j = _load(p) or {}
        if j.get('inherits'):
            found.append(j['inherits'])
    out = []
    for n in found:
        if n not in out and os.path.isfile(os.path.join(sysdir, 'BBL', 'machine', n + '.json')):
            out.append(n)
    return out


def active_preset_folder(data_dir):
    """Folder Bambu Studio loads user presets from: BambuStudio.conf app.preset_folder (the account id when
    signed in, see PresetBundle::load_user_presets). Empty -> "default"."""
    conf = _load(os.path.join(data_dir, 'BambuStudio.conf')) or {}
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
    return bool(re.search(r'bambu_optimizer\.py|printoptimizer', txt, re.I))


def _is_ours(preset):
    return isinstance(preset, dict) and (MARK in str(preset.get('description', '')) or _references_us(preset))


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
    if sys.platform != 'win32':
        return False
    try:
        import subprocess
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq bambu-studio.exe', '/NH'], capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        return 'bambu-studio.exe' in out.lower()
    except Exception:
        return False


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


def plan(data_dir, sysdir):
    """[(preset name, parent system preset, goal, parent setting_id)] for the installed printers."""
    idx = _process_index(sysdir)
    out = []
    for m in installed_printers(data_dir, sysdir):
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
                n = '%smm %s AI %s' % (lh, label, gl)
                if all(x[0] != n for x in out):
                    out.append((n, parent, goal, pj.get('setting_id', '')))
    return out


def _owned(path, j):
    base = os.path.basename(path)[:-5]
    return (base.endswith(SUFFIX) or NAME_RE.search(base)) and _is_ours(j)


def _neutralize(path, j, info, note):
    j = dict(j)
    j['post_process'] = []
    j['description'] = note
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(j, f, indent=4)
    _write_info(path[:-5] + '.info', _touch_info(info))


def _retire(path, log, backup_dir, note):
    """Remove one of our presets cloud-safely. Bambu Studio has no file-level "deleted" marker: cloud deletions
    are only queued in memory by its own Delete command (GUI_App::delete_preset_from_cloud), and a cloud preset
    that is missing locally is downloaded again on the next sync. So:
      * not synced (no setting_id): delete the files
      * synced: keep the file, clear post_process (+ note), mark it for upload -> harmless; delete it in Bambu."""
    j = _load(path)
    ipath = path[:-5] + '.info'
    info = _read_info(ipath)
    uid = os.path.basename(os.path.dirname(os.path.dirname(path)))
    if backup_dir:
        _backup(path, backup_dir, uid)
    if info.get('setting_id'):
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


def install(cmdline, data_dir=None, manifest=None, log=print, sysdir_extra=(), backup_dir=None):
    """cmdline: post-processing line containing '{goal}', e.g. '"C:\\...\\PrintOptimizer.exe" --goal {goal}'."""
    data_dir = data_dir or bambu_data_dir()
    sysdir = system_profiles_dir(data_dir, sysdir_extra)
    if not sysdir:
        log('Bambu Studio system profiles not found under %s - start Bambu Studio once, then run --install-presets again' % data_dir)
        return []
    version = (_load(os.path.join(sysdir, 'BBL.json')) or {}).get('version', '01.00.00.00')
    if not installed_printers(data_dir, sysdir):
        log('no Bambu Lab printers found in BambuStudio.conf / user machine presets - nothing to do')
        return []
    todo = plan(data_dir, sysdir)
    written = []
    for ud in user_dirs(data_dir):
        pdir = os.path.join(ud, 'process'); os.makedirs(pdir, exist_ok=True)
        uid = os.path.basename(ud)
        # 1) migrate 1.0/1.1 "... - Optimized" presets (marked, or legacy ones pointing at this tool)
        for old in sorted(glob.glob(os.path.join(pdir, '*' + SUFFIX + '.json'))):
            if _is_ours(_load(old)):
                _retire(old, log, backup_dir, 'Replaced by Print Optimizer presets named "<layer>mm <printer> AI <Goal>" '
                        '(e.g. "0.20mm H2S AI Balanced"). This preset no longer post-processes - delete it in Bambu Studio.')
        # 2) write the new set
        for name, parent, goal, base_id in todo:
            path = os.path.join(pdir, name + '.json')
            ipath = os.path.join(pdir, name + '.info')
            exists = os.path.exists(path)
            old = _load(path) if exists else None
            if exists and not _is_ours(old):
                log('skip %s: a preset with that name already exists and was not created by this tool' % path)
                continue
            line = cmdline.replace('{goal}', goal)
            if exists:      # our own preset from an earlier install: keep the user's tweaks and the cloud id
                preset = dict(old)
                preset['post_process'] = [line]
                preset['description'] = MARK + '. Runs the optimizer (--goal %s) after slicing.' % goal
                preset['inherits'] = parent
                preset['name'] = name
                info = _read_info(ipath)
            else:
                preset = {
                    'type': 'process',
                    'from': 'User',
                    'inherits': parent,
                    'is_custom_defined': '0',
                    'name': name,
                    'print_settings_id': name,
                    'description': MARK + '. Runs the optimizer (--goal %s) after slicing.' % goal,
                    'post_process': [line],
                    'version': version,
                }
                info = {'sync_info': '', 'user_id': '' if uid == 'default' else uid, 'setting_id': '', 'base_id': base_id}
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(preset, f, indent=4)
            _write_info(ipath, _touch_info(info))
            written.append(path)
            log('wrote preset: %s' % path)
    if manifest:
        prev = (_load(manifest) or {}).get('presets', [])
        with open(manifest, 'w', encoding='utf-8') as f:
            json.dump({'presets': sorted(set(prev) | set(written)), 'cmdline': cmdline}, f, indent=1)
    return written


def remove(data_dir=None, manifest=None, log=print, backup_dir=None):
    """Undo install() in every user/<id> folder: our "... AI <Goal>" and old "... - Optimized" presets only.
    Unsynced ones are deleted; cloud-synced ones are cleared (see _retire) because Bambu Studio would re-download
    a locally deleted cloud preset - which would still call the removed exe and make slicing fail."""
    data_dir = data_dir or bambu_data_dir()
    cands = set((_load(manifest) or {}).get('presets', [])) if manifest else set()
    for ud in user_dirs(data_dir):
        cands |= set(glob.glob(os.path.join(ud, 'process', '*.json')))
    done = []
    for p in sorted(cands):
        j = _load(p)
        if j is None or not _owned(p, j):
            continue     # never touch unrelated presets
        _retire(p, log, None, 'Bambu Print Optimizer was uninstalled; this preset no longer post-processes. Delete it in Bambu Studio.')
        done.append(p)
    return done
