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


def user_dirs(data_dir):
    base = os.path.join(data_dir, 'user')
    ds = [d for d in glob.glob(os.path.join(base, '*')) if os.path.isdir(d)]
    return ds or [os.path.join(base, 'default')]


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


def install(cmdline, data_dir=None, manifest=None, log=print, sysdir_extra=()):
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
            old = _load(path)
            if old is not None and MARK not in str(old.get('description', '')):
                log('skip %s: a preset with that name already exists and was not created by this tool' % path)
                continue
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
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(preset, f, indent=4)
            with open(os.path.join(pdir, name + '.info'), 'w', encoding='utf-8', newline='\n') as f:
                f.write('sync_info = \nuser_id = %s\nsetting_id = \nbase_id = %s\nupdated_time = %d\n' % (
                    '' if uid == 'default' else uid, pj.get('setting_id', ''), int(time.time())))
            written.append(path)
            log('wrote preset: %s' % path)
    if manifest:
        prev = (_load(manifest) or {}).get('presets', [])
        with open(manifest, 'w', encoding='utf-8') as f:
            json.dump({'presets': sorted(set(prev) | set(written)), 'cmdline': cmdline}, f, indent=1)
    return written


def remove(data_dir=None, manifest=None, log=print):
    data_dir = data_dir or bambu_data_dir()
    cands = set((_load(manifest) or {}).get('presets', [])) if manifest else set()
    cands |= set(glob.glob(os.path.join(data_dir, 'user', '*', 'process', '*' + SUFFIX + '.json')))
    removed = []
    for p in sorted(cands):
        j = _load(p)
        if j is None or MARK not in str(j.get('description', '')):
            continue     # never delete a preset we did not create (or one the user re-saved without our marker)
        for q in (p, p[:-5] + '.info'):
            try:
                os.remove(q)
            except OSError:
                pass
        removed.append(p)
        log('removed preset: %s' % p)
    return removed
