; VotumSecuris 安装脚本
[Setup]
AppName=VotumSecuris
AppVersion=1.1.0
AppPublisher=Nexora-Labs639
DefaultDirName={autopf}\VotumSecuris
DefaultGroupName=VotumSecuris
OutputDir=output
OutputBaseFilename=VotumSecuris_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "..\dist\VotumSecuris.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\integrity\manifest.json"; DestDir: "{app}\integrity"; Flags: ignoreversion

[Icons]
Name: "{group}\VotumSecuris"; Filename: "{app}\VotumSecuris.exe"
Name: "{commondesktop}\VotumSecuris"; Filename: "{app}\VotumSecuris.exe"

[Run]
Filename: "{app}\VotumSecuris.exe"; Description: "启动 VotumSecuris"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM VotumSecuris.exe"; Flags: runhidden
