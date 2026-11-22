"""Create / remove "<print profile> - EmberCheck <Goal>" print presets in PrusaSlicer
(e.g. "0.20 mm NORMAL (0.4 mm nozzle) @CREALITY - EmberCheck Balanced"), one per goal, based on the print profile
selected in PrusaSlicer (or the profiles named with --prusa-base).

Used by the Windows installer (EmberCheck.exe --install-prusa-presets / --remove-prusa-presets) and usable by hand.
Format follows PrusaSlicer 2.9 (src/libslic3r/Preset.cpp, PresetBundle.cpp, Config.cpp):
  * user print presets are <data_dir>/print/<preset name>.ini, file name == preset name
  * PresetCollection::load_presets applies a user preset on top of the built-in DEFAULTS, not on top of its parent:
    "inherits" only links it to the system preset in the UI. So a user preset must carry every value of its parent.
    EmberCheck therefore writes the parent's full, flattened settings: for a system preset the vendor bundle section
    and its "inherits" chain (<data_dir>/vendor/<Vendor>.ini, '*abstract*' parents, later parents win, the preset's
    own keys win), for a user preset its own .ini file (PrusaSlicer saves user presets in full).
  * post_process is a list of strings, serialized like escape_strings_cstyle(): quoted, with \\ and " escaped.
Only presets this tool created (marker in "notes" + manifest) are ever changed or removed.
"""
import datetime
import hashlib
import json
import os
import re
import sys

GOALS = [('balanced', 'Balanced'), ('speed', 'Speed'), ('quality', 'Quality')]   # = embercheck --goal choices
MARK = 'Created by EmberCheck'
NAME_RE = re.compile(r' - EmberCheck (%s)$' % '|'.join(g[1] for g in GOALS))
DROP_KEYS = ('inherits', 'renamed_from')     # bundle-only keys, never copied into a user preset


def prusa_data_dir():
    """PrusaSlicer's configuration folder (Help > Show Configuration Folder)."""
    if sys.platform == 'win32':
        return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~\\AppData\\Roaming')), 'PrusaSlicer')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/PrusaSlicer')
    flat = os.path.expanduser('~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer')     # Flathub build
    return flat if os.path.isdir(flat) else os.path.expanduser('~/.config/PrusaSlicer')


def installed(data_dir=None):
    d = data_dir or prusa_data_dir()
    return os.path.isfile(os.path.join(d, 'PrusaSlicer.ini')) or os.path.isdir(os.path.join(d, 'vendor'))


# ------------------------------------------------------------------ ini helpers
def read_ini(path):
    """{section: {key: raw value}} ('' = keys before the first section). Values stay serialized exactly as PrusaSlicer
    wrote them (split at the first '=', trimmed, like boost::property_tree's ini parser)."""
    out = {'': {}}; cur = out['']
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            s = line.strip()
            if not s or s[0] in '#;':
                continue
            if s.startswith('[') and s.endswith(']'):
                cur = out.setdefault(s[1:-1], {}); continue
            if '=' in s:
                k, v = s.split('=', 1)
                cur[k.strip()] = v.strip()
    return out


def unescape_strings(s):
    """unescape_strings_cstyle(): 'a; "b c"' -> ['a', 'b c']."""
    out = []; i = 0; n = len(s)
    if not s:
        return out
    while True:
        while i < n and s[i] in ' \t':
            i += 1
        if i >= n:
            return out
        buf = []; quoted = s[i] == '"'
        if quoted:
            i += 1
            while i < n and s[i] != '"':
                c = s[i]
                if c == '\\' and i + 1 < n:
                    i += 1; c = {'r': '\r', 'n': '\n'}.get(s[i], s[i])
                buf.append(c); i += 1
            i += 1
        else:
            while i < n and s[i] != ';':
                buf.append(s[i]); i += 1
        out.append(''.join(buf) if quoted else ''.join(buf).rstrip())
        while i < n and s[i] in ' \t':
            i += 1
        if i >= n:
            return out
        if s[i] == ';':
            i += 1
        else:
            return out


def escape_strings(values):
    """escape_strings_cstyle()."""
    res = []
    for v in values:
        if (len(values) == 1 and v == '') or any(c in v for c in ' ;\t\\"\r\n'):
            res.append('"' + v.replace('\\', '\\\\').replace('"', '\\"').replace('\r', '\\r').replace('\n', '\\n') + '"')
        else:
            res.append(v)
    return ';'.join(res)


def flatten(sections, group, name, _seen=None):
    """Resolve a vendor-bundle preset ('print', '0.20mm NORMAL @X') through its 'inherits' chain. None if absent."""
    sec = sections.get('%s:%s' % (group, name))
    if sec is None:
        return None
    seen = _seen or set()
    if name in seen:
        raise ValueError('cyclic inherits at %s' % name)
    seen = seen | {name}
    res = {}
    for parent in unescape_strings(sec.get('inherits', '')):
        p = flatten(sections, group, parent, seen)
        if p is not None:
            res.update(p)          # later parents override earlier ones
    res.update({k: v for k, v in sec.items() if k not in DROP_KEYS})
    for k in DROP_KEYS:
        res.pop(k, None)
    return res


def selected_presets(data_dir):
    ini = os.path.join(data_dir, 'PrusaSlicer.ini')
    if not os.path.isfile(ini):
        return {}
    return read_ini(ini).get('presets', {})


def _bundle_dirs(data_dir):
    dirs = [os.path.join(data_dir, 'vendor')]
    if sys.platform == 'win32':
        for env in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)'):
            if os.environ.get(env):
                dirs.append(os.path.join(os.environ[env], 'Prusa3D', 'PrusaSlicer', 'resources', 'profiles'))
    return [d for d in dirs if os.path.isdir(d)]


def resolve_base(data_dir, name):
    """(config dict, inherits value, source) for a print preset name, or (None, None, reason)."""
    up = os.path.join(data_dir, 'print', name + '.ini')
    if os.path.isfile(up):                      # a user preset: PrusaSlicer stores it in full
        cfg = dict(read_ini(up)[''])
        inh = cfg.pop('inherits', '')
        cfg.pop('renamed_from', None)
        return cfg, inh, 'user preset ' + up
    for d in _bundle_dirs(data_dir):
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith('.ini'):
                continue
            p = os.path.join(d, fn)
            try:
                secs = read_ini(p)
            except OSError:
                continue
            if ('print:' + name) in secs:
                return flatten(secs, 'print', name), name, 'system preset in ' + p
    return None, None, 'print profile "%s" not found in %s' % (name, ', '.join(_bundle_dirs(data_dir)) or data_dir)


def post_process_line(exe, script=None, args='--goal balanced'):
    q = lambda p: '"%s"' % p
    return ' '.join([q(exe)] + ([q(script)] if script else []) + ([args] if args else []))


def preset_name(base, goal_label):
    return '%s - EmberCheck %s' % (base, goal_label)


def base_of(name):
    """'X - EmberCheck Balanced' -> 'X' (the user may have an EmberCheck preset selected)."""
    return NAME_RE.sub('', name)


def _sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _load(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save(p, obj):
    if not p:
        return
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)


def _is_ours(path):
    try:
        cfg = read_ini(path)['']
    except OSError:
        return False
    return MARK in cfg.get('notes', '')


def _scripts_without_us(raw):
    return [s for s in unescape_strings(raw or '') if s.strip() and 'embercheck' not in s.lower()]


def render(cfg, inherits, cmdline, goal, version):
    """Text of a user print preset .ini (keys sorted like PrusaSlicer writes them)."""
    c = dict(cfg)
    c['inherits'] = inherits or ''
    c['post_process'] = escape_strings(_scripts_without_us(c.get('post_process')) + [cmdline])
    note = '%s %s (goal: %s). EmberCheck optimizes every G-code exported with this preset (post-processing script). ' \
           'Uninstalling EmberCheck removes this preset.' % (MARK, version, goal)
    old = c.get('notes', '')
    c['notes'] = (old + '\\n\\n' + note) if old else note
    head = '# generated by EmberCheck %s on %s (print preset for PrusaSlicer)\n' % (
        version, datetime.datetime.now().strftime('%Y-%m-%d at %H:%M:%S'))
    return head + ''.join('%s = %s\n' % (k, c[k]) for k in sorted(c))


def repoint(path, cmdline):
    """Replace only the EmberCheck post-processing entry in an existing preset (keeps the user's tweaks)."""
    with open(path, encoding='utf-8', errors='replace', newline='') as f:
        lines = f.read().splitlines(keepends=True)
    out = []; done = False
    for ln in lines:
        if re.match(r'\s*post_process\s*=', ln):
            raw = ln.split('=', 1)[1].strip()
            ln = 'post_process = %s\n' % escape_strings(_scripts_without_us(raw) + [cmdline]); done = True
        out.append(ln)
    if not done:
        out.append('post_process = %s\n' % escape_strings([cmdline]))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(''.join(out))


def prusa_running():
    if sys.platform != 'win32':
        return False
    try:
        import subprocess
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq prusa-slicer.exe', '/NH'], capture_output=True, text=True,
                           creationflags=0x08000000)
        return 'prusa-slicer.exe' in r.stdout.lower()
    except Exception:
        return False


def install(cmdline, data_dir=None, manifest=None, log=print, bases=None, version='1.5.0', stats=None):
    """Write the three EmberCheck presets for each base print profile (default: the one selected in PrusaSlicer).
    cmdline contains '{goal}'. Returns stats."""
    data_dir = data_dir or prusa_data_dir()
    st = stats if stats is not None else {}
    st.update(status='ok', written=[], kept=[], skipped=[], bases=[])
    if not installed(data_dir):
        st['status'] = 'noprusa'; log('PrusaSlicer configuration folder not found: %s' % data_dir); return st
    man = _load(manifest) or {}
    files = man.get('files', {})
    edited = set(man.get('edited', []))       # changed by the user: backed up on uninstall even after a repoint
    if not bases:
        sel = selected_presets(data_dir).get('print', '').strip()
        bases = [sel] if sel else []
        if not bases:
            bases = list(dict.fromkeys(man.get('bases', [])))
    if not bases:
        st['status'] = 'noprint'; log('no print profile selected in PrusaSlicer yet (open PrusaSlicer once and pick your printer)'); return st
    os.makedirs(os.path.join(data_dir, 'print'), exist_ok=True)
    for base in dict.fromkeys(base_of(b) for b in bases):
        cfg, inh, src = resolve_base(data_dir, base)
        if cfg is None:
            log(src); st['skipped'].append(base); continue
        log('base print profile: %s (%s)' % (base, src))
        st['bases'].append(base)
        for goal, label in GOALS:
            name = preset_name(base, label)
            path = os.path.join(data_dir, 'print', name + '.ini')
            line = cmdline.replace('{goal}', goal)
            if os.path.exists(path):
                if name not in files and not _is_ours(path):
                    log('kept %s: a preset with this name exists and was not created by EmberCheck' % name)
                    st['skipped'].append(name); continue
                if name in files and files[name] != _sha(path):
                    repoint(path, line)       # changed by the user in PrusaSlicer: keep the tweaks, update the exe path
                    files[name] = _sha(path); st['kept'].append(name)
                    edited.add(name)
                    log('updated post-processing line in %s (your changes kept)' % name)
                    continue
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(render(cfg, inh, line, goal, version))
            files[name] = _sha(path); st['written'].append(name); edited.discard(name)
            log('wrote %s' % path)
    man.update(version=version, data_dir=data_dir, files=files, edited=sorted(edited & set(files)),
               bases=list(dict.fromkeys((man.get('bases') or []) + st['bases'])))
    _save(manifest, man)
    if not st['written'] and not st['kept']:
        st['status'] = 'nothing'
    return st


def status_text(st):
    s = st.get('status')
    if s == 'noprusa':
        return 'PrusaSlicer was not found, so no PrusaSlicer presets were added.'
    if s == 'noprint':
        return 'PrusaSlicer has no print profile selected yet. Open PrusaSlicer, pick your printer, then run Start menu > EmberCheck > Add PrusaSlicer presets.'
    if s in ('error', 'nothing'):
        return 'No PrusaSlicer presets were added (see presets.log in the install folder).'
    names = st.get('written', []) + st.get('kept', [])
    bases = ', '.join('"%s"' % b for b in st.get('bases', []))
    return ('PrusaSlicer: added %d print presets based on %s, e.g. "%s". Restart PrusaSlicer and pick one under '
            'Print settings > User presets.' % (len(names), bases, names[0] if names else ''))


def remove(data_dir=None, manifest=None, log=print, backup_dir=None):
    """Delete the presets listed in the manifest (only if they still carry the EmberCheck marker). Presets the user
    changed are copied to backup_dir first."""
    man = _load(manifest) or {}
    data_dir = data_dir or man.get('data_dir') or prusa_data_dir()
    n = 0
    for name, sha in (man.get('files') or {}).items():
        path = os.path.join(data_dir, 'print', name + '.ini')
        if not os.path.exists(path):
            continue
        if not _is_ours(path) and _sha(path) != sha:
            log('kept %s: no longer an EmberCheck preset' % name); continue
        if (_sha(path) != sha or name in (man.get('edited') or [])) and backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
            import shutil
            shutil.copyfile(path, os.path.join(backup_dir, name + '.ini'))
            log('backed up your changed %s to %s' % (name, backup_dir))
        os.remove(path); n += 1
        log('removed %s' % path)
    if manifest and os.path.exists(manifest):
        os.remove(manifest)
    return n
