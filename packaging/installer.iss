; Inno Setup 6 script - per-user install of Bambu Print Optimizer (no admin rights needed).
; Build:  ISCC.exe /DAppVersion=1.1.0 /DDistDir=..\dist\PrintOptimizer /DOutDir=..\dist packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist\PrintOptimizer"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif
#define AppName "Bambu Print Optimizer"
#define AppExe "PrintOptimizer.exe"

[Setup]
AppId={{D13388CC-F03E-4F4F-95FE-FD22B0B38838}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Andrew Robinson
AppPublisherURL=https://github.com/drewrobinso/bambu-print-optimizer
AppSupportURL=https://github.com/drewrobinso/bambu-print-optimizer/issues
VersionInfoVersion={#AppVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoCompany=Andrew Robinson
VersionInfoCopyright=Copyright (c) 2026 Andrew Robinson. MIT License.
VersionInfoDescription={#AppName} Setup
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\PrintOptimizer
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DefaultGroupName=Print Optimizer
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=PrintOptimizer-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
; Releases are signed afterwards by SignPath (see .github/workflows/release.yml and packaging/signpath/), not by ISCC.
; ProductName / ProductVersion above are enforced by the SignPath artifact configuration.

[Tasks]
Name: "presets"; Description: "Add AI process presets to Bambu Studio for my printers, e.g. ""0.20mm H2S AI Balanced"" (recommended)"
Name: "startmenu"; Description: "Create Start menu shortcuts"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Print Optimizer\Print Optimizer"; Filename: "{app}\{#AppExe}"; Comment: "Optimize a sliced plate (.gcode.3mf)"; Tasks: startmenu
Name: "{userprograms}\Print Optimizer\Print Optimizer reports"; Filename: "{app}\{#AppExe}"; Parameters: "--open-reports"; Comment: "Open the reports folder"; Tasks: startmenu
Name: "{userprograms}\Print Optimizer\Uninstall Print Optimizer"; Filename: "{uninstallexe}"; Tasks: startmenu

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--install-presets"; StatusMsg: "Adding Bambu Studio presets..."; Flags: runhidden waituntilterminated; Tasks: presets
Filename: "{app}\{#AppExe}"; Parameters: "--open-reports"; Description: "Open the reports folder"; Flags: postinstall nowait skipifsilent unchecked

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--remove-presets"; Flags: runhidden waituntilterminated; RunOnceId: "RemovePresets"

[UninstallDelete]
Type: files; Name: "{app}\presets_manifest.json"
Type: files; Name: "{app}\presets.log"

[Messages]
FinishedLabel=Setup has installed [name] on your computer.%n%nRestart Bambu Studio, then pick an "AI" process preset, for example "0.20mm H2S AI Balanced" (also AI Speed / AI Quality, at 0.16 / 0.20 / 0.24 mm). Every slice with it is optimized automatically and a results card appears.%n%nOlder "... - Optimized" presets were replaced; if one is synced to your Bambu account it was switched off - delete it in Bambu Studio.%n%nReports are saved in Documents\BambuPrintOptimizer\reports.

[Code]
function BambuRunning(): Boolean;
var
  ResultCode: Integer;
  TmpFile: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := False;
  TmpFile := ExpandConstant('{tmp}\tasks.txt');
  if Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq bambu-studio.exe" /NH > "' + TmpFile + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    if LoadStringsFromFile(TmpFile, Lines) then
      for I := 0 to GetArrayLength(Lines) - 1 do
        if Pos('bambu-studio.exe', Lowercase(Lines[I])) > 0 then
          Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and WizardIsTaskSelected('presets') then
    while BambuRunning() do
      if MsgBox('Bambu Studio is running. Please close it so the new presets are picked up, then click Retry.'#13#10#13#10'Click Cancel to continue anyway (restart Bambu Studio afterwards).', mbInformation, MB_RETRYCANCEL) = IDCANCEL then
        Break;
end;
