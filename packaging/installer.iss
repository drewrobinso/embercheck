; Inno Setup 6 script - per-user install of EmberCheck (formerly Bambu Print Optimizer 1.x; no admin rights needed).
; Build:  ISCC.exe /DAppVersion=1.4.2 /DDistDir=..\dist\EmberCheck /DOutDir=..\dist packaging\installer.iss
; Silent: EmberCheck-Setup-x.y.z.exe /VERYSILENT [/PRINTERS="X1C;P1S;A1 mini"] [/TASKS="presets,startmenu"]
;         without /PRINTERS the presets are made for the printers set up in Bambu Studio (plus those chosen last time).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist\EmberCheck"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif
#define AppName "EmberCheck"
#define AppExe "EmberCheck.exe"
#define RepoUrl "https://github.com/drewrobinso/embercheck"

[Setup]
; same AppId as Bambu Print Optimizer 1.x: upgrades it in place (one entry in Apps & features)
AppId={{D13388CC-F03E-4F4F-95FE-FD22B0B38838}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Andrew Robinson
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
VersionInfoVersion={#AppVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoCompany=Andrew Robinson
VersionInfoCopyright=Copyright (c) 2026 Andrew Robinson. MIT License.
VersionInfoDescription={#AppName} Setup
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\EmberCheck
; 1.x installed to ...\Programs\PrintOptimizer: do not reuse that folder (it is migrated and removed below)
UsePreviousAppDir=no
UsePreviousGroup=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DefaultGroupName=EmberCheck
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=EmberCheck-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} - Print Optimizer for Bambu Studio
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
; Releases are signed afterwards by SignPath (see .github/workflows/release.yml and packaging/signpath/), not by ISCC.
; ProductName / ProductVersion above are enforced by the SignPath artifact configuration.

[Tasks]
Name: "presets"; Description: "Add EmberCheck process presets to Bambu Studio, e.g. ""0.20mm H2S EmberCheck Balanced"" (recommended; you pick your printers after the files are copied)"
Name: "startmenu"; Description: "Create Start menu shortcuts"

[InstallDelete]
; Start menu folder of Bambu Print Optimizer 1.x
Type: filesandordirs; Name: "{userprograms}\Print Optimizer"
Type: files; Name: "{app}\presets_status.txt"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\EmberCheck\EmberCheck"; Filename: "{app}\{#AppExe}"; Comment: "Optimize a sliced plate (.gcode.3mf)"; Tasks: startmenu
Name: "{userprograms}\EmberCheck\Add Bambu Studio presets"; Filename: "{app}\{#AppExe}"; Parameters: "--install-presets --select"; Comment: "Choose printers and create or update the EmberCheck process presets in Bambu Studio"; Tasks: startmenu
Name: "{userprograms}\EmberCheck\EmberCheck reports"; Filename: "{app}\{#AppExe}"; Parameters: "--open-reports"; Comment: "Open the reports folder"; Tasks: startmenu
Name: "{userprograms}\EmberCheck\Uninstall EmberCheck"; Filename: "{uninstallexe}"; Tasks: startmenu

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--open-reports"; Description: "Open the reports folder"; Flags: postinstall nowait skipifsilent unchecked

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--remove-presets"; Flags: runhidden waituntilterminated; RunOnceId: "RemovePresets"

[UninstallDelete]
Type: files; Name: "{app}\presets_manifest.json"
Type: files; Name: "{app}\presets.log"
Type: files; Name: "{app}\presets_*.log"
Type: files; Name: "{app}\presets_status.txt"

[Messages]
FinishedLabel=Setup has installed [name] on your computer.%n%nRestart Bambu Studio, then pick an EmberCheck process preset, for example "0.20mm H2S EmberCheck Balanced" (also EmberCheck Speed / EmberCheck Quality). Every slice with it is optimized automatically and a results card appears.%n%nReports are saved in Documents\EmberCheck\reports.

[Code]
var
  PrinterPage: TInputOptionWizardPage;
  PrinterModels: TArrayOfString;
  PresetsRan: Boolean;

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

function NextField(var S: String): String;
var
  P: Integer;
begin
  P := Pos('|', S);
  if P = 0 then begin Result := S; S := ''; end
  else begin Result := Copy(S, 1, P - 1); S := Copy(S, P + 1, Length(S)); end;
end;

procedure RunEmberCheck(Params: String);
var
  ResultCode: Integer;
begin
  Log('EmberCheck.exe ' + Params);
  if not Exec(ExpandConstant('{app}\{#AppExe}'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('could not start EmberCheck.exe: ' + SysErrorMessage(ResultCode));
end;

{ Bambu Print Optimizer 1.x lived in ...\Programs\PrintOptimizer: keep its preset backups, manifest and log,
  then remove the old folder }
procedure MigrateDir(OldDir, Tag: String);
var
  NewDir: String;
begin
  NewDir := ExpandConstant('{app}');
  if (CompareText(OldDir, NewDir) = 0) or not DirExists(OldDir) then
    Exit;
  Log('migrating ' + OldDir);
  if DirExists(OldDir + '\preset_backups') then
  begin
    if not DirExists(NewDir + '\preset_backups') then
    begin
      if not RenameFile(OldDir + '\preset_backups', NewDir + '\preset_backups') then
        Log('could not move preset_backups');
    end
    else if not RenameFile(OldDir + '\preset_backups', NewDir + '\preset_backups\from_' + Tag) then
      Log('could not move preset_backups into from_' + Tag);
  end;
  if FileExists(OldDir + '\presets_manifest.json') and not FileExists(NewDir + '\presets_manifest.json') then
    RenameFile(OldDir + '\presets_manifest.json', NewDir + '\presets_manifest.json');
  if FileExists(OldDir + '\presets.log') then
    RenameFile(OldDir + '\presets.log', NewDir + '\presets_' + Tag + '.log');
  if not DelTree(OldDir, True, True, True) then
    Log('could not remove all of ' + OldDir);
end;

procedure MigrateOldInstall();
begin
  MigrateDir(ExpandConstant('{localappdata}\Programs\PrintOptimizer'), 'printoptimizer_1x');
  { 1.x reports: renamed when the new folder does not exist yet; otherwise EmberCheck merges them on its first run }
  if DirExists(ExpandConstant('{userdocs}\BambuPrintOptimizer')) and not DirExists(ExpandConstant('{userdocs}\EmberCheck')) then
    RenameFile(ExpandConstant('{userdocs}\BambuPrintOptimizer'), ExpandConstant('{userdocs}\EmberCheck'));
end;

procedure LoadPrinters();
var
  Lines: TArrayOfString;
  I, N: Integer;
  S, Model, Short, Pre, Noz: String;
begin
  RunEmberCheck('--list-printers "' + ExpandConstant('{tmp}\printers.txt') + '"');
  SetArrayLength(PrinterModels, 0);
  if not LoadStringsFromFile(ExpandConstant('{tmp}\printers.txt'), Lines) then
    Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    S := Trim(Lines[I]);
    if S = '' then Continue;
    Model := NextField(S); Short := NextField(S); Pre := NextField(S); Noz := NextField(S);
    N := GetArrayLength(PrinterModels);
    SetArrayLength(PrinterModels, N + 1);
    PrinterModels[N] := Model;
    if Noz <> '' then
      PrinterPage.Add(Short + '   (' + Noz + ' mm nozzles)')
    else
      PrinterPage.Add(Short);
    PrinterPage.Values[N] := Pre = '1';
  end;
end;

procedure InitializeWizard();
begin
  PrinterPage := CreateInputOptionPage(wpInstalling, 'Bambu Studio printers',
    'Which printers should get EmberCheck presets?',
    'EmberCheck adds "EmberCheck Balanced / Speed / Quality" process presets for every nozzle of each checked printer. ' +
    'Printers set up in Bambu Studio are pre-checked. You can change this later with Start menu > EmberCheck > Add Bambu Studio presets.',
    False, True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MigrateOldInstall();
    if not WizardIsTaskSelected('presets') then
      { keep older presets working: point them at EmberCheck.exe (PrintOptimizer.exe was removed) }
      RunEmberCheck('--install-presets --repoint-only --quiet')
    else if WizardSilent() then
    begin
      if ExpandConstant('{param:PRINTERS|}') <> '' then
        RunEmberCheck('--install-presets --quiet --printers "' + ExpandConstant('{param:PRINTERS|}') + '"')
      else
        RunEmberCheck('--install-presets --quiet');
      PresetsRan := True;
    end
    else
    begin
      LoadPrinters();
      if GetArrayLength(PrinterModels) = 0 then
      begin
        { no Bambu Studio system profiles found: let the preset step explain it on the finish page }
        RunEmberCheck('--install-presets --quiet');
        PresetsRan := True;
      end;
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = PrinterPage.ID) and ((not WizardIsTaskSelected('presets')) or PresetsRan or (GetArrayLength(PrinterModels) = 0));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  Sel: String;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and WizardIsTaskSelected('presets') then
    while BambuRunning() do
      if MsgBox('Bambu Studio is running. Please close it so the new presets are picked up, then click Retry.'#13#10#13#10'Click Cancel to continue anyway (restart Bambu Studio afterwards).', mbInformation, MB_RETRYCANCEL) = IDCANCEL then
        Break;
  if CurPageID = PrinterPage.ID then
  begin
    Sel := '';
    for I := 0 to GetArrayLength(PrinterModels) - 1 do
      if PrinterPage.Values[I] then
      begin
        if Sel <> '' then Sel := Sel + ';';
        Sel := Sel + PrinterModels[I];
      end;
    if Sel = '' then
    begin
      if MsgBox('No printer is checked, so no EmberCheck presets will be added (your older presets are kept working).'#13#10#13#10'Continue without presets?', mbConfirmation, MB_YESNO) = IDNO then
      begin
        Result := False;
        Exit;
      end;
      RunEmberCheck('--install-presets --repoint-only --quiet');
    end
    else
      RunEmberCheck('--install-presets --quiet --printers "' + Sel + '"');
    PresetsRan := True;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Status: AnsiString;
  Msg: String;
begin
  if (CurPageID = wpFinished) and WizardIsTaskSelected('presets') then
  begin
    if LoadStringFromFile(ExpandConstant('{app}\presets_status.txt'), Status) then
      Msg := Trim(String(Status))
    else
      Msg := 'No EmberCheck presets were added (see presets.log in the install folder).';
    WizardForm.FinishedLabel.Caption := 'Setup has installed EmberCheck on your computer.' + #13#10#13#10 + Msg + #13#10#13#10 +
      'Reports are saved in Documents\EmberCheck\reports.';
    WizardForm.FinishedLabel.AutoSize := False;
    WizardForm.FinishedLabel.Height := ScaleY(170);
  end;
end;
