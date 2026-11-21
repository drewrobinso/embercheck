# PyInstaller spec - windowed (no console) one-folder build of Bambu Print Optimizer.
# Build:  python -m PyInstaller packaging/PrintOptimizer.spec --noconfirm --distpath dist --workpath build/pyi
import os, re
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
SRC = os.path.join(ROOT, 'src')
VERSION = re.search(r"^VERSION = '([^']+)'", open(os.path.join(SRC, 'bambu_optimizer.py'), encoding='utf-8').read(), re.M).group(1)

# Windows version resource (shown in file Properties and used by SignPath / SmartScreen metadata)
vt = tuple(int(x) for x in (VERSION.split('.') + ['0'] * 4)[:4])
vfile = os.path.join(ROOT, 'build', 'version_info.txt')
os.makedirs(os.path.dirname(vfile), exist_ok=True)
open(vfile, 'w', encoding='utf-8').write(open(os.path.join(SPECPATH, 'version_info.tmpl'), encoding='utf-8').read()
                                        .replace('@VT@', repr(vt)).replace('@VERSION@', VERSION))

a = Analysis(
    [os.path.join(SRC, 'bambu_optimizer.py')],
    pathex=[SRC],
    binaries=[],
    datas=[(os.path.join(SPECPATH, 'icon.ico'), '.'), (os.path.join(ROOT, 'LICENSE'), '.')],
    hiddenimports=['secrets', 'ui', 'progress', 'bambu_presets', 'report', 'materials', 'emitter', 'optimizer', 'gcode_model', 'project_info'],
    excludes=['matplotlib', 'scipy', 'pandas', 'PIL', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='PrintOptimizer',
    console=False,              # GUI subsystem: no console window when Bambu Studio runs it
    icon=os.path.join(SPECPATH, 'icon.ico'),
    version=vfile,
    upx=False,                  # UPX-packed exes trip antivirus heuristics; keep plain
)
coll = COLLECT(exe, a.binaries, a.datas, name='PrintOptimizer', upx=False)
