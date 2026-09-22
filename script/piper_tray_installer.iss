#define MyAppName "Piper Tray"
#define MyAppExeName "PiperTray.exe"
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build_windows_installer.ps1
#endif

[Setup]
AppId={{A5A223C5-5A81-4E0A-8D66-5A2E55A26A91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\PiperTray
DefaultGroupName=Piper Tray
OutputDir=..\dist
OutputBaseFilename=PiperTraySetup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\PiperTray.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Piper Tray"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Piper Tray"; Flags: nowait postinstall skipifsilent
