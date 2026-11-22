# PyInstaller spec - windowed (no console) one-folder build of EmberCheck.
# Build:  python -m PyInstaller packaging/EmberCheck.spec --noconfirm --distpath dist --workpath build/pyi
import os, re
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
SRC = os.path.join(ROOT, 'src')
VERSION = re.search(r"^VERSION = '([^']+)'", open(os.path.join(SRC, 'embercheck.py'), encoding='utf-8').read(), re.M).group(1)

# Windows version resource (shown in file Properties and used by SignPath / SmartScreen metadata)
vt = tuple(int(x) for x in (VERSION.split('.') + ['0'] * 4)[:4])
vfile = os.path.join(ROOT, 'build', 'version_info.txt')
os.makedirs(os.path.dirname(vfile), exist_ok=True)
open(vfile, 'w', encoding='utf-8').write(open(os.path.join(SPECPATH, 'version_info.tmpl'), encoding='utf-8').read()
                                        .replace('@VT@', repr(vt)).replace('@VERSION@', VERSION))

a = Analysis(
    [os.path.join(SRC, 'embercheck.py')],
    pathex=[SRC],
    binaries=[],
    datas=[(os.path.join(SPECPATH, 'icon.ico'), '.'), (os.path.join(ROOT, 'LICENSE'), '.'), (os.path.join(SRC, 'assets'), 'assets')],
    hiddenimports=['secrets', 'ui', 'progress', 'bambu_presets', 'prusa_presets', 'report', 'materials', 'emitter', 'optimizer', 'gcode_model', 'project_info', 'stamp'],
    excludes=['matplotlib', 'scipy', 'pandas', 'PIL', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='EmberCheck',
    console=False,              # GUI subsystem: no console window when Bambu Studio runs it
    icon=os.path.join(SPECPATH, 'icon.ico'),
    version=vfile,
    upx=False,                  # UPX-packed exes trip antivirus heuristics; keep plain
)
coll = COLLECT(exe, a.binaries, a.datas, name='EmberCheck', upx=False)
