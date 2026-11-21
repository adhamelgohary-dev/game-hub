#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{BCE7FA2A-7A55-487B-9BC4-2EA83958BF9A}
AppName=Game Hub
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Game Hub
DefaultGroupName=Game Hub
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=GameHub-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\GameHub.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\GameHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Game Hub"; Filename: "{app}\GameHub.exe"; WorkingDir: "{app}"
Name: "{group}\Third-party notices"; Filename: "{app}\_internal\third-party\THIRD_PARTY_NOTICES.txt"

[Run]
Filename: "{app}\GameHub.exe"; Description: "Launch Game Hub"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
