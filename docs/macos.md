# Running EmberCheck on macOS

macOS support is a **preview and is untested**. There is no Mac app or installer yet. These steps use the same Python zip published with each Windows release. Please report how it goes: [github.com/drewrobinso/embercheck/issues](https://github.com/drewrobinso/embercheck/issues).

## 1. Install Python 3.11+

Use the installer from [python.org](https://www.python.org/downloads/) (includes Tk, which the results card needs), or Homebrew:

```
brew install python python-tk
```

The system `/usr/bin/python3` is a stub until the Xcode Command Line Tools are installed (`xcode-select --install`).

Then install the two packages EmberCheck uses:

```
python3 -m pip install --user shapely numpy
```

Or, from the unzipped folder: `python3 -m pip install --user -r requirements.txt`.

## 2. Unzip the Python package

Download `EmberCheck-<version>-python.zip` from [Releases](https://github.com/drewrobinso/embercheck/releases) and unzip it to a stable folder, for example `~/EmberCheck`. The files sit at the zip root (`embercheck.py` next to `requirements.txt`).

**Gatekeeper / quarantine.** A zip from a browser download is often marked with a quarantine attribute. Python scripts usually still run. If macOS blocks them, or `python3 embercheck.py` fails with an "untrusted" / "developer cannot be verified" message, clear the attribute on the unzipped folder (this only removes the download flag; it does not disable Gatekeeper):

```
xattr -dr com.apple.quarantine ~/EmberCheck
```

## 3. Post-processing script in Bambu Studio

Close Bambu Studio if it is open. In the process preset, open **Others** and set **Post-processing scripts** to one line, with a trailing semicolon (the form Bambu Studio expects on macOS). It appends the temporary G-code path and runs the line through your shell; EmberCheck edits that file in place.

```
/usr/bin/python3 "/Users/<you>/EmberCheck/embercheck.py" --goal balanced;
```

Use `/opt/homebrew/bin/python3` or `/usr/local/bin/python3` if that is the interpreter you installed packages into. Quote any path that contains a space. For the other goals, use `--goal speed` or `--goal quality`.

Print, Send and Export should then use the post-processed file, and the preview should show it. Check any output with:

```
python3 ~/EmberCheck/embercheck.py --check-stamp /path/to/plate.gcode.3mf
```

## 4. Optional: add the EmberCheck presets

With Bambu Studio closed, from the unzipped folder:

```
python3 ~/EmberCheck/embercheck.py --install-presets
```

That writes the `... EmberCheck Balanced / Speed / Quality` process presets into every Bambu Studio user folder under `~/Library/Application Support/BambuStudio/user/`. It looks up printers from `BambuStudio.conf` and from Bambu Studio's system profiles (the app bundle, then the copied `system` folder). Add `--select` to pick printers in a window, or `--printers "X1C;P1S;A1 mini"`. `--remove-presets` undoes it.

From a git checkout you can run `scripts/install_macos.sh` instead (same command; pass any extra flags through).

## 5. Standalone

```
python3 ~/EmberCheck/embercheck.py ~/path/plate.gcode.3mf
```

writes `plate.optimized.gcode.3mf`. Plain `.gcode` works too (`-o out.gcode`, or in place).

Reports go to `~/Documents/EmberCheck/reports`. The receipt log is `~/Library/Application Support/EmberCheck/runs.log`.

## What is not included yet

- No signed Mac app, `.dmg`, or Homebrew cask.
- No testing on a Mac (Apple Silicon or Intel). Tk windows, Gatekeeper, and Bambu Studio's script field may still need tweaks.
- The Windows installer and `EmberCheck.exe` are Windows-only.
