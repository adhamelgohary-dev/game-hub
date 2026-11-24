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

function IsLocalDrivePath(const DirPath: string): Boolean;
begin
  Result :=
    (Length(DirPath) >= 3) and
    (Pos('/', DirPath) = 0) and
    (Pos('..', DirPath) = 0) and
    (((DirPath[1] >= 'A') and (DirPath[1] <= 'Z')) or ((DirPath[1] >= 'a') and (DirPath[1] <= 'z'))) and
    (DirPath[2] = ':') and
    (DirPath[3] = '\');
end;

function IsDirEmpty(const DirPath: string): Boolean;
var
  FindRec: TFindRec;
begin
  Result := True;
  if FindFirst(AddBackslash(DirPath) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := False;
          Break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function IsForbiddenDestination(const DirPath: string): Boolean;
var
  Norm: string;
  UserProfileDir: string;
  DesktopDir: string;
  LocalAppDir: string;
  DataDir: string;
  LegacyDataDir: string;
begin
  Result := True;
  Norm := RemoveBackslashUnlessRoot(Trim(DirPath));
  if not IsLocalDrivePath(Norm) then
    Exit;
  // Reject bare drive roots like C:\ or D:\
  if Length(Norm) <= 3 then
    Exit;

  UserProfileDir := RemoveBackslashUnlessRoot(ExpandConstant('{%USERPROFILE|}'));
  DesktopDir := RemoveBackslashUnlessRoot(ExpandConstant('{userdesktop}'));
  LocalAppDir := RemoveBackslashUnlessRoot(ExpandConstant('{localappdata}'));
  DataDir := RemoveBackslashUnlessRoot(ExpandConstant('{localappdata}\GameRewind'));
  LegacyDataDir := RemoveBackslashUnlessRoot(ExpandConstant('{localappdata}\GameHub'));

  if (CompareText(Norm, UserProfileDir) = 0) or
     (CompareText(Norm, DesktopDir) = 0) or
     (CompareText(Norm, LocalAppDir) = 0) or
     (CompareText(Norm, DataDir) = 0) or
     (CompareText(Norm, LegacyDataDir) = 0) then
    Exit;

  Result := False;
end;

function IsDirWritable(DirPath: string): Boolean;
var
  ProbeDir: string;
  ParentDir: string;
  ProbeFile: string;
begin
  Result := False;
  ProbeDir := RemoveBackslashUnlessRoot(Trim(DirPath));
  if not IsLocalDrivePath(ProbeDir) then
    Exit;

  while (not DirExists(ProbeDir)) do
  begin
    ParentDir := RemoveBackslashUnlessRoot(ExtractFileDir(ProbeDir));
    if (ParentDir = '') or (CompareText(ParentDir, ProbeDir) = 0) then
      Break;
    ProbeDir := ParentDir;
  end;

  if not DirExists(ProbeDir) then
    Exit;

  ProbeFile := AddBackslash(ProbeDir) + 'gamerewind-write-probe-' + GetDateTimeString('yyyymmddhhnnss', #0, #0) + '.tmp';
  if SaveStringToFile(ProbeFile, 'ok', False) then
  begin
    if DeleteFile(ProbeFile) then
      Result := True;
  end;
end;

function ValidateInstallDir(const RawDir: string; var ErrMsg: string): Boolean;
var
  TargetDir: string;
begin
  Result := False;
  ErrMsg := '';
  TargetDir := RemoveBackslashUnlessRoot(Trim(RawDir));
  if (TargetDir = '') or (not IsLocalDrivePath(TargetDir)) then
  begin
    ErrMsg := 'Please choose a valid local folder on a drive (for example D:\GameRewind).';
    Exit;
  end;
  if IsForbiddenDestination(TargetDir) then
  begin
    ErrMsg := 'Please install GameRewind into its own dedicated subfolder (for example Desktop\GameRewind or D:\GameRewind) instead of a drive root, Desktop directly, or your data folder.';
    Exit;
  end;
  if DirExists(TargetDir) and (not IsDirEmpty(TargetDir)) and
     (not FileExists(AddBackslash(TargetDir) + 'GameRewind.exe')) and
     (not FileExists(AddBackslash(TargetDir) + 'GameHub.exe')) then
  begin
    ErrMsg := 'The chosen folder is not empty and contains other files. Please choose an empty folder or create a new subfolder (for example ...\GameRewind).';
    Exit;
  end;
  if not IsDirWritable(TargetDir) then
  begin
    ErrMsg :=
      'GameRewind does not have permission to write to the selected folder.' + #13#10 +
      'Because GameRewind installs per-user without administrator rights, please choose a writable folder (for example in your user folder, Desktop\GameRewind, or another drive).';
    Exit;
  end;
  Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ErrMsg: string;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if not ValidateInstallDir(WizardDirValue, ErrMsg) then
    begin
      MsgBox(ErrMsg, mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function ExtractUninstallExePath(const RawCmd: string): string;
var
  S: string;
  P: Integer;
begin
  Result := '';
  S := Trim(RawCmd);
  if S = '' then
    Exit;
  if S[1] = '"' then
  begin
    Delete(S, 1, 1);
    P := Pos('"', S);
    if P > 1 then
      Result := Copy(S, 1, P - 1);
  end
  else
  begin
    P := Pos(' ', S);
    if P > 1 then
      Result := Copy(S, 1, P - 1)
    else
      Result := S;
  end;
end;

function RunValidatedQuietUninstaller(const RegKey: string): Boolean;
var
  RawUninstall: string;
  InstallLoc: string;
  UninstallExe: string;
  UninstallDir: string;
  BaseName: string;
  ResultCode: Integer;
begin
  Result := True;
  if not RegQueryStringValue(HKCU, RegKey, 'UninstallString', RawUninstall) then
    Exit;

  UninstallExe := Trim(ExtractUninstallExePath(RawUninstall));
  // Validate strictly BEFORE touching the filesystem (prevents UNC/SMB/proxy execution).
  if (UninstallExe = '') or (not IsLocalDrivePath(UninstallExe)) then
    Exit;
  BaseName := Lowercase(ExtractFileName(UninstallExe));
  if (Pos('unins', BaseName) <> 1) or (ExtractFileExt(BaseName) <> '.exe') then
    Exit;

  if not RegQueryStringValue(HKCU, RegKey, 'InstallLocation', InstallLoc) then
    Exit;
  InstallLoc := RemoveBackslashUnlessRoot(Trim(InstallLoc));
  if (InstallLoc = '') or IsForbiddenDestination(InstallLoc) then
    Exit;

  UninstallDir := RemoveBackslashUnlessRoot(ExtractFileDir(UninstallExe));
  if CompareText(UninstallDir, InstallLoc) <> 0 then
    Exit;
  if not FileExists(UninstallExe) then
    Exit;

  if Exec(
    UninstallExe,
    '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    Result := (ResultCode = 0)
  else
    Result := False;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  PrevInstallDir: string;
  NewInstallDir: string;
  LegacyStartMenuDir: string;
  ErrMsg: string;
begin
  Result := '';

  // Enforce destination validation in /SILENT and /VERYSILENT modes too.
  if not ValidateInstallDir(ExpandConstant('{app}'), ErrMsg) then
  begin
    Result := ErrMsg;
    Exit;
  end;

  // 1. Cleanly remove any previous Game Hub installation (shortcuts, binaries, uninstall entry).
  //    Never touches %LOCALAPPDATA%\GameHub so GameRewind can migrate user data automatically.
  if RunValidatedQuietUninstaller(LegacyGameHubUninstallKey) then
  begin
    if RegKeyExists(HKCU, LegacyGameHubUninstallKey) then
      RegDeleteKeyIncludingSubkeys(HKCU, LegacyGameHubUninstallKey);
  end;

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
    begin
      if not RunValidatedQuietUninstaller(CurrentGameRewindUninstallKey) then
      begin
        Result := 'Please close any running GameRewind window before moving the installation to a new folder.';
        Exit;
      end;
    end;
  end;
end;
