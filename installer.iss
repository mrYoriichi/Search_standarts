; Inno Setup script: wraps the PyInstaller build folder into one Search_standarts_Setup.exe.
;
; What the installer does:
;   - copies dist\Search_standarts\ into Program Files\Search_standarts
;   - puts shortcuts into the Start menu and (optionally) on the desktop
;   - adds an entry to "Programs and Features" (automatic uninstaller)
;
; User data (app.db, indexed PDFs) lives in %APPDATA%\Search_standarts,
; so uninstalling/reinstalling the app does NOT touch it.
;
; Building the installer (after pyinstaller build.spec):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; Result: installer\Search_standarts_Setup.exe

#define MyAppName "Search_standarts"
#define MyAppVersion "0.5.3"
#define MyAppPublisher "Search_standarts"
#define MyAppExeName "Search_standarts.exe"

[Setup]
; AppId uniquely identifies the app for updates/uninstall — do NOT change between versions.
AppId={{8F3A1C7E-2B4D-4E6A-9C1F-7A5B2D8E4F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Per-user install (into %LOCALAPPDATA%\Programs) -> NO administrator rights needed.
; With lowest, {autopf} automatically = {localappdata}\Programs.
PrivilegesRequired=lowest
; The app is 64-bit (torch/docling) — install into the 64-bit Program Files.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
OutputDir=installer
; Версия в имени файла — чтобы при скачивании было видно, что ставишь.
OutputBaseFilename=Search_standarts_Setup_{#MyAppVersion}
; Uninstaller icon — taken from the .exe itself.
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Optional desktop shortcut (a checkbox in the wizard).
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; On upgrade the old _internal stays as installed by the previous version;
; files removed from the new build would linger there forever (hundreds of
; MB, and a stale-DLL risk). The new build re-copies the folder in full.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; The whole PyInstaller one-folder build: .exe + _internal with all deps and models.
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app right after installation.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
