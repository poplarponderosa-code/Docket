; Docket installer (Inno Setup 6).  Build it with build_installer.bat.
;
; Installs for the current user only, so no admin prompt (the wizard offers
; "install for all users" too). Adds a Start menu entry, an optional desktop
; shortcut, and an uninstaller in Settings > Apps. Uninstalling leaves the
; person's lists in %APPDATA%\Docket, so reinstalling brings them back.
;
; For a new version: change MyAppVersion below (and __version__ in docket\__init__.py).

#define MyAppName "Docket"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "Docket"
#define MyAppExeName "Docket.exe"

[Setup]
; Keep this AppId the same forever: it's how Windows knows a new installer is an update.
AppId={{8E3B6C2A-5D7F-4C1E-9A2B-3F6D4E8C1A70}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_output
OutputBaseFilename=Docket-Setup-{#MyAppVersion}
SetupIconFile=assets\docket.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Docket holds this name while it runs, so Setup and Uninstall ask to close it first.
AppMutex=DocketRunningMutex
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Docket\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Docket adds itself to Windows startup when it runs; remove that entry on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Docket"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; After an update started from inside Docket (a quiet install), open Docket again.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--updated"; Flags: nowait; Check: WizardSilent
