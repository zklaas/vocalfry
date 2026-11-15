; Inno Setup script: the Windows installer for VocalFry.
; Built by .github/workflows/release.yml from PyInstaller's dist\VocalFry folder:
;   iscc /DAppVersion=1.0.0 packaging\vocalfry.iss
; Installs for the current user only (no administrator rights), adds a Start-menu
; entry and an uninstaller (Settings > Apps).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{E097D5EB-70C5-5DFE-B611-1FE3DF2ACF95}
AppName=VocalFry
AppVersion={#AppVersion}
AppPublisher=Zachary Klaas
AppPublisherURL=https://github.com/zklaas/vocalfry
DefaultDirName={localappdata}\Programs\VocalFry
DefaultGroupName=VocalFry
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=VocalFry-Setup-Windows
SetupIconFile=..\icons\vocalfry.ico
UninstallDisplayIcon={app}\VocalFry.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\VocalFry\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\VocalFry"; Filename: "{app}\VocalFry.exe"
Name: "{userdesktop}\VocalFry"; Filename: "{app}\VocalFry.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\VocalFry.exe"; Description: "Start VocalFry"; Flags: nowait postinstall skipifsilent
