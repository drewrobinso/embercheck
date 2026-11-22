#!/bin/bash
# Local (unsigned) Windows build on Linux using Wine: PyInstaller + Inno Setup inside a Wine prefix.
# The official release build runs natively on GitHub's windows-latest runner (.github/workflows/release.yml).
# One-time setup of the prefix: see README "Building".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
export WINEPREFIX="${WINEPREFIX:-/workspace/winbuild/prefix}" WINEDEBUG=-all
export DISPLAY="${DISPLAY:-:77}"
PY='C:\Python312\python.exe'; ISCC='C:\InnoSetup\ISCC.exe'
VERSION=$(sed -n "s/^VERSION = '\(.*\)'/\1/p" src/embercheck.py)
rm -rf build/pyi dist/EmberCheck
wine "$PY" -m PyInstaller packaging/EmberCheck.spec --noconfirm --clean --distpath dist --workpath build/pyi --log-level WARN
wine "$ISCC" /Q "/DAppVersion=$VERSION" packaging/installer.iss
python3 scripts/make_portable_zip.py
ls -la dist
