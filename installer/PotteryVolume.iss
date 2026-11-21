; Installer for the per-user PotteryVolume launcher.

[Setup]
AppId={{2D8A1936-4F0A-42D1-9F17-3C67A8F5B2E1}
AppName=PotteryVolume
AppVersion=0.1.2
AppPublisher=PotteryVolume
DefaultDirName={localappdata}\Programs\PotteryVolume
DisableDirPage=no
DefaultGroupName=PotteryVolume
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename=PotteryVolume-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=PotteryVolume

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成する"; GroupDescription: "追加アイコン:"; Flags: checkedonce

[Files]
Source: "..\dist\PotteryVolume.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\PotteryVolume"; Filename: "{app}\PotteryVolume.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\PotteryVolume"; Filename: "{app}\PotteryVolume.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\PotteryVolume.exe"; Parameters: "--prepare-only"; Flags: waituntilterminated
Filename: "{app}\PotteryVolume.exe"; Description: "インストール後にPotteryVolumeを起動する"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\payload"
Type: files; Name: "{app}\.last-successful-release"
Type: files; Name: "{app}\.last-successful-release.tmp"
Type: files; Name: "{app}\.prepare.lock"
Type: files; Name: "{app}\PotteryVolume-GUI-Windows.zip.*.part"

[Code]
procedure RegisterExtraCloseApplicationsResources;
var
  FindRec: TFindRec;
  Executable: String;
  ResourceRegistered: Boolean;
begin
  if FindFirst(ExpandConstant('{app}\payload\*'), FindRec) then
  try
    repeat
      if ((FindRec.Attributes and $10) <> 0) and
         (FindRec.Name <> '.') and (FindRec.Name <> '..') then
      begin
        Executable := ExpandConstant('{app}\payload\' + FindRec.Name +
          '\PotteryVolume_gui\PotteryVolume_gui.exe');
        if FileExists(Executable) then
          ResourceRegistered := RegisterExtraCloseApplicationsResource(False, Executable);
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;
