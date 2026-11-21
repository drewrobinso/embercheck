"""dist/BambuPrintOptimizer-<ver>-python.zip: flat zip of the Python sources (files at the zip root),
for people who prefer their own Python install (unzip to C:\\BambuPrintOptimizer)."""
import os, re, zipfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ver = re.search(r"^VERSION = '([^']+)'", open(os.path.join(ROOT, 'src', 'bambu_optimizer.py'), encoding='utf-8').read(), re.M).group(1)
os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
out = os.path.join(ROOT, 'dist', 'BambuPrintOptimizer-%s-python.zip' % ver)
files = sorted(f for f in os.listdir(os.path.join(ROOT, 'src')) if f.endswith('.py'))
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(os.path.join(ROOT, 'src', f), f)
    for f in ('README.md', 'LICENSE', 'requirements.txt'):
        z.write(os.path.join(ROOT, f), f)
    z.write(os.path.join(ROOT, 'packaging', 'icon.ico'), 'icon.ico')
print('wrote', out, files)
