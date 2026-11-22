# Native Windows build (used by CI on windows-latest; also works on a dev PC).
# Requires: Python 3.12 x64, Inno Setup 6 (choco install innosetup).  Output: dist\EmberCheck-Setup-<ver>.exe
param([switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
python -m pip install --disable-pip-version-check -r requirements-build.txt
$version = (Select-String -Path src\embercheck.py -Pattern "^VERSION = '(.+)'").Matches[0].Groups[1].Value
python -m PyInstaller packaging\EmberCheck.spec --noconfirm --clean --distpath dist --workpath build\pyi
if (-not $SkipInstaller) {
  $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $iscc) { throw 'Inno Setup 6 not found (choco install innosetup)' }
  & $iscc /Q "/DAppVersion=$version" packaging\installer.iss
  if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }
}
python scripts\make_portable_zip.py
if ($env:GITHUB_OUTPUT) { "version=$version" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8 }
