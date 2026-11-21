"""Create / remove "<system preset> - Optimized" process presets in Bambu Studio.

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

SUFFIX = ' - Optimized'
MARK = 'Created by Bambu Print Optimizer'   # stored in the preset "description"


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


def install(cmdline, data_dir=None, manifest=None, log=print, sysdir_extra=(), backup_dir=None):
    data_dir = data_dir or bambu_data_dir()
    sysdir = system_profiles_dir(data_dir, sysdir_extra)
    if not sysdir:
        log('Bambu Studio system profiles not found under %s - start Bambu Studio once, then run --install-presets again' % data_dir)
        return []
    version = (_load(os.path.join(sysdir, 'BBL.json')) or {}).get('version', '01.00.00.00')
    printers = installed_printers(data_dir, sysdir)
    if not printers:
        printers = ['Bambu Lab H2S 0.4 nozzle'] if os.path.isfile(os.path.join(sysdir, 'BBL', 'machine', 'Bambu Lab H2S 0.4 nozzle.json')) else []
        log('no printers found in BambuStudio.conf - defaulting to %s' % printers)
    parents = []
    for m in printers:
        mj = _load(os.path.join(sysdir, 'BBL', 'machine', m + '.json')) or {}
        dp = mj.get('default_print_profile')
        if dp and dp not in parents and os.path.isfile(os.path.join(sysdir, 'BBL', 'process', dp + '.json')):
            parents.append(dp)
    written = []
    for ud in user_dirs(data_dir):
        pdir = os.path.join(ud, 'process'); os.makedirs(pdir, exist_ok=True)
        uid = os.path.basename(ud)
        for parent in parents:
            pj = _load(os.path.join(sysdir, 'BBL', 'process', parent + '.json')) or {}
            name = parent + SUFFIX
            path = os.path.join(pdir, name + '.json')
            ipath = os.path.join(pdir, name + '.info')
            exists = os.path.exists(path)
            old = _load(path) if exists else None
            if exists and not _is_ours(old):
                log('skip %s: a preset with that name already exists and was not created by this tool' % path)
                continue
            info = _read_info(ipath) if exists else {}
            if exists:
                legacy = MARK not in str(old.get('description', ''))
                if legacy:   # e.g. the old manual setup: python.exe ...\bambu_optimizer.py, no marker
                    b = _backup(path, backup_dir, uid)
                    log('upgrading legacy preset %s (backup: %s)' % (path, b))
                preset = dict(old)   # keep the user's own tweaks; only fix post-processing + marker
                preset['post_process'] = [cmdline]
                preset['description'] = MARK + '. Runs the optimizer after slicing.'
                preset.setdefault('inherits', parent)
                preset.setdefault('version', version)
                preset['name'] = name
            else:
                preset = {
                    'type': 'process',
                    'from': 'User',
                    'inherits': parent,
                    'is_custom_defined': '0',
                    'name': name,
                    'print_settings_id': name,
                    'description': MARK + '. Runs the optimizer after slicing.',
                    'post_process': [cmdline],
                    'version': version,
                }
                info = {'sync_info': '', 'user_id': '' if uid == 'default' else uid, 'setting_id': '',
                        'base_id': pj.get('setting_id', '')}
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


def remove(data_dir=None, manifest=None, log=print):
    """Undo install() in every user/<id> folder. Only "* - Optimized" presets that are ours (marker or a
    post-processing line pointing at this tool) are touched.
    * not synced to the Bambu cloud: files deleted
    * synced (has setting_id): deleting locally would make Bambu Studio re-download the cloud copy, which would
      still call the removed exe and make slicing fail - so the post-processing line is cleared instead
      (marked for upload). Delete it in Bambu Studio if you no longer want it."""
    data_dir = data_dir or bambu_data_dir()
    cands = set((_load(manifest) or {}).get('presets', [])) if manifest else set()
    for ud in user_dirs(data_dir):
        cands |= set(glob.glob(os.path.join(ud, 'process', '*' + SUFFIX + '.json')))
    removed = []
    for p in sorted(cands):
        j = _load(p)
        if j is None or not os.path.basename(p).endswith(SUFFIX + '.json') or not _is_ours(j):
            continue     # never touch unrelated presets
        ipath = p[:-5] + '.info'
        info = _read_info(ipath)
        if info.get('setting_id'):
            j['post_process'] = []
            j['description'] = 'Bambu Print Optimizer was uninstalled; this preset no longer post-processes. Safe to delete.'
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(j, f, indent=4)
            _write_info(ipath, _touch_info(info))
            log('neutralized cloud-synced preset (post-processing cleared): %s' % p)
        else:
            for q in (p, ipath):
                try:
                    os.remove(q)
                except OSError:
                    pass
            log('removed preset: %s' % p)
        removed.append(p)
    return removed
