# SignPath Foundation application: draft answers

Form: https://signpath.org/apply. It is an embedded HubSpot form; its field list could not be read from the box, so these answers cover the questions the Foundation's published conditions (https://signpath.org/terms) require. Paste them into whichever fields the form shows.

> **Before applying (read first)**
> - SignPath Foundation requires that the project is **already released in the form that should be signed**, and that executable projects have **some verifiable reputation**.
> - Recommended order:
>   1. Push the repo publicly.
>   2. Publish the CI-built **unsigned** installer as release `v1.1.0` (the workflow builds and uploads it; attach it to a release by hand, or temporarily allow unsigned releases).
>   3. Let it collect some users or feedback (for example, a post on the Bambu Lab forum or r/BambuLab).
>   4. Then apply.
> - Turn on **MFA** on GitHub (and later on SignPath). This is mandatory for every team member.
> - Placeholders still to fill in: the final repo URL (assumed below to be `https://github.com/drewrobinso/bambu-print-optimizer`) and the contact email.

---

**Project name:** Bambu Print Optimizer

**Repository URL:** https://github.com/drewrobinso/bambu-print-optimizer

**Homepage / download page:** https://github.com/drewrobinso/bambu-print-optimizer (README) and https://github.com/drewrobinso/bambu-print-optimizer/releases

**License:** MIT (OSI-approved). All components are open source. There is no proprietary code and no commercial dual licensing.

**Short description:**
A free, local post-processing tool for Bambu Studio, the 3D-printer slicer.
- After slicing, it runs a simplified thermal model of the print and flags layers that will be too hot or too cold.
- It adjusts only feedrates and part-cooling fan values within the printer's and filament's limits. It also slows unsupported overhangs and reports stringing-prone travel moves.
- It verifies that extrusion is unchanged before writing, and shows a results card plus an offline HTML report.
- It is a free, offline alternative to cloud services like Helio Additive. No data leaves the PC.

**What will be signed:**
- `PrintOptimizer.exe`: a PyInstaller-built windowed executable (the project's own Python code plus the PyInstaller bootloader).
- `PrintOptimizer-Setup-<version>.exe`: an Inno Setup per-user installer.
- Bundled third-party runtime files are **not** signed with the project certificate; they are included unmodified from upstream. These are the CPython runtime (PSF-signed), numpy, shapely/GEOS and Tcl/Tk.
- The artifact configurations restrict signing to exactly these two files and enforce ProductName "Bambu Print Optimizer" and ProductVersion = the release version. See `packaging/signpath/app.xml` and `installer.xml`.

**Build system:**
- GitHub Actions on GitHub-hosted `windows-latest` runners (`.github/workflows/release.yml`), with pinned dependencies (`requirements-build.txt`).
- The workflow builds with PyInstaller and Inno Setup, self-tests the frozen exe, uploads the unsigned artifacts, and submits them with `signpath/github-action-submit-signing-request`.
- The signed installer is published only as a draft GitHub release, after manual approval in SignPath.

**Does the software include an installer / uninstaller?**
Yes, with Inno Setup.
- It installs per user, with no admin rights, to `%LOCALAPPDATA%\Programs\PrintOptimizer`.
- It shows an explicit, opt-out checkbox before it changes anything outside its folder: *"Add '- Optimized' process presets to Bambu Studio for my printers"*.
  - This writes small preset JSON files in Bambu Studio's user preset folder.
  - It never modifies existing presets.
- The uninstaller removes the app, the shortcuts, and only the presets it created (identified by a marker).

**System changes:** Only the files listed above. There are no services, drivers, scheduled tasks, registry autoruns, PATH changes or elevation.

**Network / privacy:**
- The program makes no network connections at all: no telemetry, no update checks.
- README privacy statement: "This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it."

**Security tooling?** No. It contains no hacking, scanning or exploitation features.

**Team and roles:** The project has a single maintainer.
- Author / committer: Andrew Robinson (GitHub: @drewrobinso)
- Reviewer: Andrew Robinson (reviews every external pull request)
- Approver for signing requests: Andrew Robinson
- MFA is enabled on GitHub and will be enabled on SignPath.

**Code signing policy on the homepage:** Yes, in the README section "Code signing policy", which contains:
- "Free code signing provided by SignPath.io, certificate by SignPath Foundation"
- the team roles
- the privacy statement

**Reputation / users:** *(fill in at application time)*
- Release downloads, GitHub stars, forum or Reddit threads, and so on.
- The project was first released in November 2026.

**Why code signing is needed:**
- Users are 3D-printing hobbyists on Windows, most of whom are not developers.
- Unsigned installers trigger SmartScreen "Windows protected your PC" warnings and antivirus heuristics, especially for PyInstaller-built executables.
- Bambu Studio runs the program automatically after every slice, so users need to be able to trust the binary's origin.

**Contact:** Andrew Robinson, <email to fill in>
