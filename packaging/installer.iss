; Maple Helper installer (Inno Setup 6). Per-user install: no admin rights, silent self-updates.
; Build: ISCC packaging\installer.iss   (after PyInstaller has produced dist\Maple Helper)

#define AppName "Maple Helper"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
; releases ship lzma2/ultra; CI passes /DCompression=lzma2/fast (build.ps1 -FastInstaller) to save build time
#ifndef Compression
  #define Compression "lzma2/ultra"
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
; look: Windows 11 style that follows the system light/dark setting, like the app itself,
; over a frosted image of the game world; mascot and app icon from the brand
WizardStyle=modern dynamic windows11
ShowLanguageDialog=no
DisableWelcomePage=no
LanguageDetectionMethod=locale
WizardBackColor=#F5F5F7
WizardBackColorDynamicDark=#1C1C1E
WizardBackImageFile=installer-art\back-light.png
WizardBackImageFileDynamicDark=installer-art\back-dark.png
WizardImageFile=installer-art\side.png
WizardImageFileDynamicDark=installer-art\side.png
WizardSmallImageFile=installer-art\small.png
WizardSmallImageFileDynamicDark=installer-art\small.png
WizardImageAlphaFormat=defined
Compression={#Compression}
SolidCompression=yes
; compress on the runner's 4 cores instead of one
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
CloseApplications=force
; the app's own .pyd/.pyc files count too, not only exe/dll
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
; the app waits while this exists, so a relaunch can't land in the middle of an update
SetupMutex=MapleHelperSetup
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
; after a silent self-update, start the app again: in the tray when it updated on quit (the player closed it),
; with the chat open after "Update now" (the app passes /LAUNCHARGS=--updated)
Filename: "{app}\Maple Helper.exe"; Parameters: "{param:LAUNCHARGS|--background}"; Flags: nowait; Check: WizardSilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
hebrew.WelcomeLabel1=ברוכים הבאים ל-Maple Helper
hebrew.WelcomeLabel2=העוזר האישי שלכם ב-MapleStory.%n%nההתקנה לוקחת פחות מדקה ולא דורשת הרשאות מנהל.
hebrew.FinishedHeadingLabel=Maple Helper מוכן!
hebrew.FinishedLabel=בכניסה הראשונה נחבר את ה-AI שלכם (Claude או Codex) וניצור את הדמות שלכם.%n%nבתוך המשחק, לחצו F9 כדי לפתוח ולסגור את הצ'אט.
english.WelcomeLabel1=Welcome to Maple Helper
english.WelcomeLabel2=Your personal MapleStory assistant.%n%nSetup takes under a minute and needs no admin rights.
english.FinishedHeadingLabel=Maple Helper is ready!
english.FinishedLabel=On first launch we'll connect your AI (Claude or Codex) and set up your character.%n%nIn game, press F9 to open and close the chat.

[Code]
// An update runs right after the app quits: wait (up to 30 s) until it has really exited,
// so no file is still in use while it is replaced (a half-updated install otherwise).
function InitializeSetup(): Boolean;
var
  i: Integer;
begin
  i := 0;
  while CheckForMutexes('MapleHelperRunning') and (i < 60) do
  begin
    Sleep(500);
    i := i + 1;
  end;
  Result := True;
end;
