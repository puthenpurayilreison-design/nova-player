; Installer di NOVA (Inno Setup 6). Generato da crea_exe.bat
#define AppVer "4.6"

[Setup]
AppId={{FD90169A-6126-4E57-B9DE-6D4BF8E63B74}
AppName=NOVA
AppVersion={#AppVer}
AppVerName=NOVA {#AppVer}
AppPublisher=NOVA
AppPublisherURL=https://github.com/puthenpurayilreison-design/nova-player
DefaultDirName={localappdata}\Programs\NOVA
DefaultGroupName=NOVA
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=NOVA-Setup
SetupIconFile=..\assets\nova.ico
UninstallDisplayIcon={app}\NOVA.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\NOVA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\NOVA"; Filename: "{app}\NOVA.exe"
Name: "{autodesktop}\NOVA"; Filename: "{app}\NOVA.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NOVA.exe"; Description: "{cm:LaunchProgram,NOVA}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\bin"
