# Privacy policy — EmberCheck

*Applies to EmberCheck (formerly Bambu Print Optimizer) from version 1.4.2: the Windows app `EmberCheck.exe`, its installer `EmberCheck-Setup-<version>.exe` and the Python version. Last updated 2026-11-21.*

**This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.**

## What EmberCheck collects and sends
Nothing. EmberCheck has no telemetry, analytics, crash reporting, update check, accounts or ads. It makes no network connections of its own. Everything runs locally on your PC.

## Links it opens, only when you click them
EmberCheck opens your web browser only when you click one of these:
- **Support this project** on the results card → the Buy Me a Coffee page https://buymeacoffee.com/drewrobinso
- **How to verify** on the results card → the documentation page https://github.com/drewrobinso/embercheck/blob/main/docs/verify.md
- **Full report** → a local HTML file on your PC (no web request)

Those websites have their own privacy policies (Buy Me a Coffee, GitHub). EmberCheck sends them nothing apart from what your browser normally sends when it opens a page.

## Files it writes on your PC
- The G-code that Bambu Studio hands it, or the file you choose (optimized in place or saved as a copy)
- Reports, the summary JSON and `optimizer.log` in `Documents\EmberCheck\reports\`
- The receipt log `%LOCALAPPDATA%\EmberCheck\runs.log`: one line per optimized file with the time, file name, goal, print times and the file's SHA-256 hash
- Its install folder `%LOCALAPPDATA%\Programs\EmberCheck\`, including preset backups and the preset log
- With the installer's preset option: process preset files in `%APPDATA%\BambuStudio\user\<id>\process\`

When it detects your printers, EmberCheck reads `BambuStudio.conf`. It uses only the printer and preset names from that file. It never logs, copies or sends the file's contents (which include printer access codes).

You can delete any of these files at any time. Uninstalling removes the program, its shortcuts and the presets it created. Your reports, the receipt log and the preset backups are kept.

## Bambu Studio and the Bambu cloud
If you are signed in to Bambu Studio with preset sync turned on, Bambu Studio itself may upload the EmberCheck presets to your Bambu account, as it does with any user preset. That is Bambu Studio's behaviour, covered by Bambu Lab's privacy policy. EmberCheck has no part in it.

## Contact
Questions: open an issue at https://github.com/drewrobinso/embercheck/issues
