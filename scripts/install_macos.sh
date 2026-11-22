#!/bin/bash
# Install EmberCheck process presets into Bambu Studio on macOS.
# Uses embercheck.py --install-presets (only EmberCheck-marked presets are written).
# Extra arguments are passed through, e.g. ./scripts/install_macos.sh --select
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$HERE/embercheck.py" ]]; then
  SCRIPT="$HERE/embercheck.py"
elif [[ -f "$HERE/../embercheck.py" ]]; then
  SCRIPT="$HERE/../embercheck.py"
elif [[ -f "$HERE/../src/embercheck.py" ]]; then
  SCRIPT="$HERE/../src/embercheck.py"
else
  echo "Cannot find embercheck.py (looked next to this script, in the parent folder, and in ../src)." >&2
  exit 1
fi
SCRIPT="$(cd "$(dirname "$SCRIPT")" && pwd)/$(basename "$SCRIPT")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper is for macOS. On other systems run: python3 \"$SCRIPT\" --install-presets" >&2
  exit 1
fi

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.11+ from python.org or Homebrew (see docs/macos.md)." >&2
  exit 1
fi

BAMBU="${HOME}/Library/Application Support/BambuStudio"
if [[ ! -d "$BAMBU" ]]; then
  echo "Bambu Studio's data folder was not found:" >&2
  echo "  $BAMBU" >&2
  echo "Install Bambu Studio and open it once, then re-run this script." >&2
  exit 1
fi

if pgrep -x BambuStudio >/dev/null 2>&1; then
  echo "Please close Bambu Studio first, then re-run this script." >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT" --install-presets "$@"
