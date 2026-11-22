# Code signing policy — EmberCheck

> **Status: pending.** EmberCheck has applied for, or is applying for, free code signing from SignPath Foundation. Until that is approved, releases are **unsigned** and marked as such. When signing is approved, the attribution below applies to every signed release:
>
> *Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).*

## Official repository
https://github.com/drewrobinso/embercheck is the only official source of EmberCheck. Signed binaries are published only on its [Releases](https://github.com/drewrobinso/embercheck/releases) page.

## What is signed
Only this project's own files:
- `EmberCheck.exe`: the application (PyInstaller, windowed)
- `EmberCheck-Setup-<version>.exe`: the installer (Inno Setup, per-user)

Both carry the product name **EmberCheck** and the release version as file metadata (ProductName, ProductVersion, FileVersion). The SignPath artifact configurations in [`packaging/signpath/`](packaging/signpath/) only sign files with exactly this metadata. Bundled open-source runtime files (CPython, numpy, shapely/GEOS, Tcl/Tk) are shipped unmodified as published upstream and are not signed with this project's certificate.

## How releases are signed
- Signed files are built **only** by the GitHub Actions release workflow ([`.github/workflows/release.yml`](.github/workflows/release.yml)) on GitHub-hosted runners, from a tagged commit in this repository.
- Local and developer builds are **never** signed with the SignPath Foundation certificate. Local test signing uses a throw-away self-signed certificate, and its output is never distributed.
- Every signing request is **approved manually**, release by release, by an approver in SignPath.
- Signed installers are first published as a draft release and checked (signature status, SHA-256) before release.

## Team roles
| Role | Person |
|---|---|
| Author / committer | Andrew Robinson ([@drewrobinso](https://github.com/drewrobinso)) |
| Reviewer | Andrew Robinson ([@drewrobinso](https://github.com/drewrobinso)): reviews every external contribution before merge |
| Approver (signing requests) | Andrew Robinson ([@drewrobinso](https://github.com/drewrobinso)) |

All team members use multi-factor authentication on GitHub, and will on SignPath once the project is set up there.

## Privacy
See the [privacy policy](PRIVACY.md). This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.
