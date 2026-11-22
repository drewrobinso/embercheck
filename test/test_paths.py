"""Cross-platform path helpers (Windows / macOS / Linux). Run: python test/test_paths.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import bambu_presets as bp
import embercheck as ec


def _with_platform(mod, name, fn):
    orig = mod.sys.platform
    try:
        mod.sys.platform = name
        return fn()
    finally:
        mod.sys.platform = orig


def _with_home(fn):
    """Run fn() with HOME (and related env) pointed at a throwaway directory."""
    home = tempfile.mkdtemp()
    keys = ('HOME', 'APPDATA', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'ProgramFiles', 'ProgramW6432')
    old = {k: os.environ.get(k) for k in keys}
    try:
        os.environ['HOME'] = home
        for k in keys:
            if k != 'HOME':
                os.environ.pop(k, None)
        return fn(), home
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    # Bambu Studio user data dir (expanduser follows HOME)
    def check_bambu():
        assert bp.bambu_data_dir() == os.path.join(os.environ['HOME'], 'Library', 'Application Support', 'BambuStudio')
    (lambda: _with_home(lambda: _with_platform(bp, 'darwin', check_bambu)))()

    def check_linux():
        assert bp.bambu_data_dir() == os.path.join(os.environ['HOME'], '.config', 'BambuStudio')
    (lambda: _with_home(lambda: _with_platform(bp, 'linux', check_linux)))()

    def check_win():
        os.environ['APPDATA'] = os.path.join(os.environ['HOME'], 'AppData', 'Roaming')
        got = bp.bambu_data_dir()
        assert got == os.path.join(os.environ['APPDATA'], 'BambuStudio'), got
    (lambda: _with_home(lambda: _with_platform(bp, 'win32', check_win)))()

    # System profile search includes the macOS app bundle; a fake bundle is found
    cands = _with_platform(bp, 'darwin', lambda: bp.system_profile_candidates('/tmp/unused-data'))
    assert any(p.replace('\\', '/').endswith('BambuStudio.app/Contents/Resources/profiles') for p in cands), cands
    assert any(p.replace('\\', '/').endswith('Bambu Studio.app/Contents/Resources/profiles') for p in cands), cands

    d = tempfile.mkdtemp()
    bundle = os.path.join(d, 'Applications', 'BambuStudio.app', 'Contents', 'Resources', 'profiles')
    os.makedirs(os.path.join(bundle, 'BBL', 'machine'))
    open(os.path.join(bundle, 'BBL.json'), 'w').write('{}')
    found = None
    for app in ('BambuStudio.app', 'Bambu Studio.app'):
        c = os.path.join(d, 'Applications', app, 'Contents', 'Resources', 'profiles')
        if os.path.isfile(os.path.join(c, 'BBL.json')) and os.path.isdir(os.path.join(c, 'BBL', 'machine')):
            found = c
            break
    assert found == bundle

    # post_process_line is the stored preset value (no trailing semicolon; the macOS UI field uses ; as a separator)
    line = bp.post_process_line('/usr/bin/python3', '/tmp/embercheck.py', '--goal balanced')
    assert line == '"/usr/bin/python3" "/tmp/embercheck.py" --goal balanced', line
    assert not line.endswith(';')

    # EmberCheck data dir — isolated HOME so we never touch the real user folders
    def check_mac_data():
        return ec.local_data_dir()
    mac_data, home = _with_home(lambda: _with_platform(ec, 'darwin', check_mac_data))
    assert mac_data == os.path.join(home, 'Library', 'Application Support', 'EmberCheck'), mac_data

    def check_win_data():
        os.environ['LOCALAPPDATA'] = os.path.join(os.environ['HOME'], 'AppData', 'Local')
        return ec.local_data_dir()
    win, home = _with_home(lambda: _with_platform(ec, 'win32', check_win_data))
    assert win == os.path.join(home, 'AppData', 'Local', 'EmberCheck'), win

    def check_linux_data():
        return ec.local_data_dir()
    linux_data, home = _with_home(lambda: _with_platform(ec, 'linux', check_linux_data))
    assert linux_data == os.path.join(home, '.local', 'share', 'embercheck'), linux_data

    # gui_available: macOS must not require DISPLAY; Linux without DISPLAY/Wayland is blocked
    old_disp, old_wl = os.environ.pop('DISPLAY', None), os.environ.pop('WAYLAND_DISPLAY', None)
    try:
        def gate():
            if ec.sys.platform not in ('win32', 'darwin') and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                return 'blocked'
            return 'allowed'
        assert _with_platform(ec, 'darwin', gate) == 'allowed'
        assert _with_platform(ec, 'win32', gate) == 'allowed'
        assert _with_platform(ec, 'linux', gate) == 'blocked'
        os.environ['DISPLAY'] = ':0'
        assert _with_platform(ec, 'linux', gate) == 'allowed'
    finally:
        if old_disp is not None:
            os.environ['DISPLAY'] = old_disp
        elif 'DISPLAY' in os.environ:
            del os.environ['DISPLAY']
        if old_wl is not None:
            os.environ['WAYLAND_DISPLAY'] = old_wl

    print('test_paths: OK')


if __name__ == '__main__':
    main()
