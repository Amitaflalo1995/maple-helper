; Maple Helper installer (Inno Setup 6). Per-user install: no admin rights, silent self-updates.
; Build: ISCC packaging\installer.iss   (after PyInstaller has produced dist\Maple Helper)

#define AppName "Maple Helper"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{4B526220-22E4-45D2-88B7-C62A0B7385E4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Maple Helper
AppPublisherURL=https://github.com/Amitaflalo1995/maple-helper
AppSupportURL=https://github.com/Amitaflalo1995/maple-helper/issues
DefaultDirName={localappdata}\Programs\Maple Helper
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=MapleHelper-Setup
SetupIconFile=..\assets\brand\app.ico
UninstallDisplayIcon={app}\Maple Helper.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/ultra
SolidCompression=yes
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Maple Helper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Maple Helper.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Maple Helper.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Maple Helper.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; after a silent self-update, start the app again
Filename: "{app}\Maple Helper.exe"; Flags: nowait; Check: WizardSilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
