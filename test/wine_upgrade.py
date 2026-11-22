"""Upgrade test under Wine: install an old Bambu Print Optimizer 1.x installer, add a user preset that
calls its exe, then install EmberCheck over it (silent) and check the result; finally uninstall EmberCheck.
usage: python3 test/wine_upgrade.py OLD_SETUP.exe NEW_SETUP.exe [--printers "X1C;H2S"] [--no-presets]
Needs WINEPREFIX with Bambu Studio's AppData (system profiles + BambuStudio.conf). Never prints the conf."""
import glob, json, os, subprocess, sys
PFX = os.environ.get('WINEPREFIX', '/workspace/winbuild/prefix')
U = os.path.join(PFX, 'drive_c', 'users', os.environ.get('WINEUSER', 'box'))
LOCAL = os.path.join(U, 'AppData', 'Local'); ROAM = os.path.join(U, 'AppData', 'Roaming')
OLD_DIR = os.path.join(LOCAL, 'Programs', 'PrintOptimizer'); NEW_DIR = os.path.join(LOCAL, 'Programs', 'EmberCheck')
SM = os.path.join(ROAM, 'Microsoft', 'Windows', 'Start Menu', 'Programs')
BAMBU = os.path.join(ROAM, 'BambuStudio', 'user')
KEY = r'HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{D13388CC-F03E-4F4F-95FE-FD22B0B38838}_is1'
ENV = dict(os.environ, WINEPREFIX=PFX, WINEDEBUG='-all')


def wine(*args):
    return subprocess.run(['wine'] + list(args), env=ENV, capture_output=True, text=True, timeout=600)


def presets():
    return sorted(os.path.relpath(p, BAMBU) for p in glob.glob(os.path.join(BAMBU, '*', 'process', '*.json')))


def reg(name):
    r = wine('reg', 'query', KEY, '/v', name)
    for ln in r.stdout.splitlines():
        if name in ln and 'REG_' in ln:
            return ln.split('REG_SZ', 1)[-1].strip()
    return None


def main():
    old, new = sys.argv[1], sys.argv[2]
    OLD_EXE, OLD_SM, old_tag = 'PrintOptimizer.exe', 'Print Optimizer', ' AI '
    printers = sys.argv[sys.argv.index('--printers') + 1] if '--printers' in sys.argv else None
    no_presets = '--no-presets' in sys.argv
    res = {}; ok = True

    def check(name, cond, info=''):
        nonlocal ok
        res[name] = 'OK' if cond else 'FAIL %s' % info
        ok = ok and bool(cond)
    wine(old, '/VERYSILENT', '/SUPPRESSMSGBOXES')
    old_presets = presets()
    check('old installed', os.path.exists(os.path.join(OLD_DIR, OLD_EXE)) and os.path.isdir(os.path.join(SM, OLD_SM)))
    res['presets after old install'] = [p for p in old_presets if old_tag in p or 'Optimized' in p][:3] + ['... %d total' % len(old_presets)]
    # a tweak in one old preset must be carried over
    tw = next((p for p in old_presets if old_tag in p), None)
    if tw:
        j = json.load(open(os.path.join(BAMBU, tw))); j['wall_loops'] = '5'; json.dump(j, open(os.path.join(BAMBU, tw), 'w'), indent=4)
    mine = os.path.join(BAMBU, 'default', 'process', 'My own PETG.json')
    os.makedirs(os.path.dirname(mine), exist_ok=True)
    json.dump({'name': 'My own PETG', 'inherits': '0.20mm Standard @BBL H2S',
               'post_process': ['"%s\\%s" --goal quality --no-accel' % ('C:\\users\\box\\AppData\\Local\\Programs\\' + os.path.basename(OLD_DIR), OLD_EXE)]},
              open(mine, 'w'), indent=4)
    kdoc = os.path.join(U, 'Documents', 'BambuPrintOptimizer', 'reports'); os.makedirs(kdoc, exist_ok=True)
    open(os.path.join(kdoc, 'old_report.html'), 'w').write('<p>old</p>')
    args = [new, '/VERYSILENT', '/SUPPRESSMSGBOXES'] + (['/PRINTERS=%s' % printers] if printers else []) + \
        (['/TASKS=startmenu'] if no_presets else [])
    r = wine(*args)
    check('new installer exit 0', r.returncode == 0, r.returncode)
    check('old folder removed', not os.path.exists(OLD_DIR), os.listdir(OLD_DIR) if os.path.exists(OLD_DIR) else '')
    check('EmberCheck.exe installed', os.path.exists(os.path.join(NEW_DIR, 'EmberCheck.exe')))
    check('old Start menu folder removed', not os.path.exists(os.path.join(SM, 'Print Optimizer')))
    sm = sorted(os.listdir(os.path.join(SM, 'EmberCheck'))) if os.path.isdir(os.path.join(SM, 'EmberCheck')) else []
    check('EmberCheck Start menu', len(sm) == 4, sm); res['start menu'] = sm
    check('preset backups migrated', os.path.isdir(os.path.join(NEW_DIR, 'preset_backups')))
    check('reports migrated', os.path.exists(os.path.join(U, 'Documents', 'EmberCheck', 'reports', 'old_report.html')))
    check('uninstall entry = EmberCheck', (reg('DisplayName') or '').startswith('EmberCheck'), reg('DisplayName'))
    check('uninstall entry location', 'EmberCheck' in (reg('InstallLocation') or ''), reg('InstallLocation'))
    now = presets()
    res['EmberCheck presets'] = len([p for p in now if ' EmberCheck ' in p])
    if no_presets:
        check('no EmberCheck presets (task off)', not any(' EmberCheck ' in p for p in now))
    else:
        check('EmberCheck presets written', any(' EmberCheck ' in p for p in now))
        check('AI presets retired', not any(' AI ' in p for p in now), [p for p in now if ' AI ' in p][:3])
        if tw:
            nw = os.path.join(BAMBU, tw.replace(old_tag, ' EmberCheck '))
            check('tweak carried over', os.path.exists(nw) and json.load(open(nw)).get('wall_loops') == '5', nw)
        for p in now:
            if ' EmberCheck ' in p:
                j = json.load(open(os.path.join(BAMBU, p)))
                if 'EmberCheck.exe' not in j['post_process'][0] or not j.get('compatible_printers'):
                    check('EmberCheck preset content', False, p); break
        else:
            check('EmberCheck preset content (EmberCheck.exe, compatible_printers)', True)
        if printers:
            shorts = [s.strip() for s in printers.replace(',', ';').split(';') if s.strip()]
            for sh in shorts:
                check('presets for %s' % sh, any(' %s EmberCheck ' % sh in p or ' %s 0.' % sh in p for p in now))
    pp = json.load(open(mine))['post_process'][0]
    check('own preset repointed to EmberCheck.exe', 'EmberCheck\\EmberCheck.exe" --goal quality --no-accel' in pp, pp)
    st = os.path.join(NEW_DIR, 'presets_status.txt')
    res['finish text'] = open(st, encoding='utf-8').read().strip()[:300] if os.path.exists(st) else None
    # uninstall
    r = wine(os.path.join(NEW_DIR, 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES')
    after = presets()
    check('uninstall: EmberCheck presets removed', not any(' EmberCheck ' in p for p in after), [p for p in after if ' EmberCheck ' in p][:3])
    check('uninstall: EmberCheck.exe removed', not os.path.exists(os.path.join(NEW_DIR, 'EmberCheck.exe')))
    check('uninstall: Start menu removed', not os.path.isdir(os.path.join(SM, 'EmberCheck')))
    check('uninstall: registry entry removed', reg('DisplayName') is None)
    for k, v in res.items():
        print('%-48s %s' % (k, v))
    print('wine_upgrade: %s (%s -> %s)' % ('PASS' if ok else 'FAIL', os.path.basename(old), os.path.basename(new)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
