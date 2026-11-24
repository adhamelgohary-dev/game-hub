#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif
#ifndef OutputFilename
  #define OutputFilename "GameRewind-Setup-v" + AppVersion
#endif

[Setup]
AppId={{9F4C6E1D-3B8A-4D2E-A157-8C0B2E7A4D91}
AppName=GameRewind
AppVersion={#AppVersion}
AppPublisher=GameRewind
AppPublisherURL=https://github.com/adhamelgohary-dev/game-rewind
DefaultDirName={localappdata}\Programs\GameRewind
DefaultGroupName=GameRewind
DisableDirPage=no
UsePreviousAppDir=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#OutputFilename}
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\GameRewind.exe
SetupIconFile=assets\GameRewind.ico
WizardStyle=modern
WizardImageFile=assets\wizard-sidebar.bmp
WizardSmallImageFile=assets\wizard-header.bmp

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\GameRewind\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; Remove any legacy autostart values on install/upgrade and uninstall; never create one.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "GameHub"; ValueType: none; Flags: deletevalue uninsdeletevalue dontcreatekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "GameRewind"; ValueType: none; Flags: deletevalue uninsdeletevalue dontcreatekey

[Icons]
Name: "{group}\GameRewind"; Filename: "{app}\GameRewind.exe"; WorkingDir: "{app}"; AppUserModelID: "GameRewind.Desktop"
Name: "{group}\Third-party notices"; Filename: "{app}\_internal\third-party\THIRD_PARTY_NOTICES.txt"
Name: "{userdesktop}\GameRewind"; Filename: "{app}\GameRewind.exe"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "GameRewind.Desktop"

[Run]
Filename: "{app}\GameRewind.exe"; Description: "Launch GameRewind"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
const
  LegacyGameHubUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{BCE7FA2A-7A55-487B-9BC4-2EA83958BF9A}_is1';
  CurrentGameRewindUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{9F4C6E1D-3B8A-4D2E-A157-8C0B2E7A4D91}_is1';

function IsDirWritable(DirPath: string): Boolean;
var
  ProbeDir: string;
  ProbeFile: string;
begin
  Result := False;
  ProbeDir := RemoveBackslashUnlessRoot(Trim(DirPath));
  if ProbeDir = '' then
    Exit;

  while (not DirExists(ProbeDir)) and (Length(ProbeDir) > 3) do
    ProbeDir := RemoveBackslashUnlessRoot(ExtractFileDir(ProbeDir));

  if not DirExists(ProbeDir) then
    Exit;

  ProbeFile := AddBackslash(ProbeDir) + 'gamerewind-write-probe-' + GetDateTimeString('yyyymmddhhnnss', #0, #0) + '.tmp';
  if SaveStringToFile(ProbeFile, 'ok', False) then
  begin
    DeleteFile(ProbeFile);
    Result := True;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  TargetDir: string;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    TargetDir := Trim(WizardDirValue);
    if (TargetDir = '') or (Pos('..', TargetDir) > 0) then
    begin
      MsgBox('Please choose a valid local folder for GameRewind.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not IsDirWritable(TargetDir) then
    begin
      MsgBox(
        'GameRewind does not have permission to write to the selected folder.' + #13#10 +
        'Because GameRewind installs per-user without administrator rights, please choose a writable folder (for example in your user folder, Desktop, or another drive).',
        mbError,
        MB_OK
      );
      Result := False;
      Exit;
    end;
  end;
end;

procedure RunQuietUninstallerForKey(const RegKey: string);
var
  UninstallExe: string;
  ResultCode: Integer;
begin
  if RegQueryStringValue(HKCU, RegKey, 'UninstallString', UninstallExe) then
  begin
    UninstallExe := RemoveQuotes(Trim(UninstallExe));
    if (UninstallExe <> '') and FileExists(UninstallExe) then
    begin
      Exec(
        UninstallExe,
        '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
        '',
        SW_HIDE,
        ewWaitUntilTerminated,
        ResultCode
      );
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  PrevInstallDir: string;
  NewInstallDir: string;
  LegacyStartMenuDir: string;
begin
  Result := '';

  // 1. Cleanly remove any previous Game Hub installation (shortcuts, binaries, uninstall entry).
  //    Never touches %LOCALAPPDATA%\GameHub so GameRewind can migrate user data automatically.
  RunQuietUninstallerForKey(LegacyGameHubUninstallKey);
  if RegKeyExists(HKCU, LegacyGameHubUninstallKey) then
    RegDeleteKeyIncludingSubkeys(HKCU, LegacyGameHubUninstallKey);

  LegacyStartMenuDir := ExpandConstant('{userprograms}\Game Hub');
  if DirExists(LegacyStartMenuDir) then
    DelTree(LegacyStartMenuDir, True, True, True);
  if FileExists(ExpandConstant('{userdesktop}\Game Hub.lnk')) then
    DeleteFile(ExpandConstant('{userdesktop}\Game Hub.lnk'));

  // 2. If upgrading GameRewind into a DIFFERENT destination folder, cleanly remove the old folder first.
  if RegQueryStringValue(HKCU, CurrentGameRewindUninstallKey, 'InstallLocation', PrevInstallDir) then
  begin
    PrevInstallDir := RemoveBackslashUnlessRoot(Trim(PrevInstallDir));
    NewInstallDir := RemoveBackslashUnlessRoot(Trim(ExpandConstant('{app}')));
    if (PrevInstallDir <> '') and (CompareText(PrevInstallDir, NewInstallDir) <> 0) then
      RunQuietUninstallerForKey(CurrentGameRewindUninstallKey);
  end;
end;
