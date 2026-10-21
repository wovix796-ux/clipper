; Setup für Clipper (Inno Setup 6). Wird von build.py gebaut: python build.py --setup
; build.py übergibt AppVersion, SourceDir (fertige App), IconFile und OutDir.
; Installiert ohne Adminrechte nach %LOCALAPPDATA%\Programs\Clipper, wie build.py selbst.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{A84DDE11-FA48-4664-8D15-D04E196FB1C4}
AppName=Clipper
AppVersion={#AppVersion}
AppVerName=Clipper {#AppVersion}
AppPublisher=wovix796-ux
AppPublisherURL=https://github.com/wovix796-ux/clipper
AppSupportURL=https://github.com/wovix796-ux/clipper/issues
DefaultDirName={localappdata}\Programs\Clipper
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=Clipper-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Clipper.exe
UninstallDisplayName=Clipper
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Läuft Clipper gerade, schließt das Setup es vor dem Ersetzen der Dateien
CloseApplications=force
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
en.FfmpegTask=Install ffmpeg (needed for recording)
en.FfmpegStatus=Installing ffmpeg …

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "ffmpeg"; Description: "{cm:FfmpegTask}"; Check: NeedsFfmpeg

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Reste einer älteren Version (andere Bibliotheken) vor dem Kopieren entfernen
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Clipper"; Filename: "{app}\Clipper.exe"
Name: "{autodesktop}\Clipper"; Filename: "{app}\Clipper.exe"; Tasks: desktopicon

[Run]
; ffmpeg nicht mitliefern (GPL), sondern über winget nachinstallieren, falls es fehlt
Filename: "winget.exe"; Parameters: "install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --disable-interactivity"; StatusMsg: "{cm:FfmpegStatus}"; Tasks: ffmpeg; Flags: runhidden waituntilterminated
Filename: "{app}\Clipper.exe"; Description: "{cm:LaunchProgram,Clipper}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/f /im Clipper.exe"; Flags: runhidden; RunOnceId: "StopClipper"

[UninstallDelete]
; Autostart-Eintrag, den Clipper selbst anlegt. Clips und Einstellungen bleiben erhalten.
Type: files; Name: "{userstartup}\Clipper.vbs"

[Code]
function FfmpegFound(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Microsoft\WinGet\Links\ffmpeg.exe'))
    or (FileSearch('ffmpeg.exe', GetEnv('PATH')) <> '');
end;

function NeedsFfmpeg(): Boolean;
begin
  Result := not FfmpegFound();
end;
