; Inno Setup-скрипт: оборачивает папку сборки PyInstaller в один Search_standarts_Setup.exe.
;
; Что делает установщик:
;   - копирует dist\Search_standarts\ в Program Files\Search_standarts
;   - кладёт ярлыки в меню «Пуск» и (по выбору) на рабочий стол
;   - добавляет запись в «Установка и удаление программ» (автоматический деинсталлятор)
;
; Данные пользователя (app.db, проиндексированные PDF) живут в %APPDATA%\Search_standarts,
; поэтому удаление/переустановка программы их НЕ трогает.
;
; Сборка установщика (после pyinstaller build.spec):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; Результат: installer\Search_standarts_Setup.exe

#define MyAppName "Search_standarts"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Search_standarts"
#define MyAppExeName "Search_standarts.exe"

[Setup]
; AppId уникально идентифицирует программу для апдейтов/удаления — НЕ менять между версиями.
AppId={{8F3A1C7E-2B4D-4E6A-9C1F-7A5B2D8E4F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Ставим в Program Files → нужны права администратора.
PrivilegesRequired=admin
; Приложение 64-битное (torch/docling) — ставим в 64-битный Program Files.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
OutputDir=installer
OutputBaseFilename=Search_standarts_Setup
; Иконка деинсталлятора — из самого .exe.
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Необязательный ярлык на рабочем столе (галочка в мастере).
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Вся папка сборки PyInstaller (one-folder): .exe + _internal со всеми зависимостями и моделями.
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Предложить запустить приложение сразу после установки.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
