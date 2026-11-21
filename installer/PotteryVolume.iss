; PotteryVolume GUI installer. The GUI payload is downloaded at install time.

#ifndef AppVersion
  #error AppVersion must be supplied by build.ps1
#endif
#ifndef CommitSha
  #error CommitSha must be supplied by build.ps1
#endif

#define PayloadBaseUrl "https://file.ayane0857.net/app/doki/windows"

[Setup]
AppId={{2D8A1936-4F0A-42D1-9F17-3C67A8F5B2E1}
AppName=PotteryVolume
AppVersion={#AppVersion}
AppVerName=PotteryVolume {#AppVersion}
AppComments=ビルドコミット: {#CommitSha}
AppPublisher=PotteryVolume
AppPublisherURL=https://github.com/ayane0857/doki
AppUpdatesURL=https://github.com/ayane0857/doki/releases
DefaultDirName={localappdata}\Programs\PotteryVolume
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
AppMutex=Local\PotteryVolumeAppMutex
SetupMutex=Local\PotteryVolumeSetupMutex
SetupLogging=yes
UsePreviousAppDir=yes
UninstallDisplayName=PotteryVolume
UninstallDisplayIcon={app}\PotteryVolume_gui\PotteryVolume_gui.exe
OutputDir=..\dist
OutputBaseFilename=PotteryVolume-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchiveExtraction=full

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成する"; GroupDescription: "追加アイコン:"; Flags: checkedonce

[Icons]
Name: "{autoprograms}\PotteryVolume"; Filename: "{app}\PotteryVolume_gui\PotteryVolume_gui.exe"; WorkingDir: "{app}\PotteryVolume_gui"
Name: "{autodesktop}\PotteryVolume"; Filename: "{app}\PotteryVolume_gui\PotteryVolume_gui.exe"; WorkingDir: "{app}\PotteryVolume_gui"; Tasks: desktopicon

[Run]
Filename: "{app}\PotteryVolume_gui\PotteryVolume_gui.exe"; Description: "インストール後にPotteryVolumeを起動する"; Flags: postinstall nowait skipifsilent; Check: not IsUpdateMode

[UninstallDelete]
Type: filesandordirs; Name: "{app}\PotteryVolume_gui"
Type: filesandordirs; Name: "{app}\.PotteryVolume-staging"
Type: filesandordirs; Name: "{app}\.PotteryVolume-backup"

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ReleaseVersion: String;
  StagingRoot: String;
  PayloadZip: String;
  PreparedPayload: Boolean;

function IsHexadecimal(const Value: String): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := False;
  if (Length(Value) <> 40) and (Length(Value) <> 64) then
    Exit;
  for I := 1 to Length(Value) do begin
    C := Value[I];
    if not (((C >= '0') and (C <= '9')) or
      ((C >= 'a') and (C <= 'f')) or ((C >= 'A') and (C <= 'F'))) then
      Exit;
  end;
  Result := True;
end;

function NormalizeReleaseText(const Value: String): String;
begin
  Result := Trim(Value);
end;

function FirstField(const Value: String): String;
var
  I: Integer;
begin
  Result := Trim(Value);
  for I := 1 to Length(Result) do
    if (Result[I] = ' ') or (Result[I] = #9) or
      (Result[I] = #13) or (Result[I] = #10) then begin
      Result := Copy(Result, 1, I - 1);
      Exit;
    end;
end;

function IsUpdateMode: Boolean;
begin
  Result := CompareText(ExpandConstant('{param:UPDATE|0}'), '1') = 0;
end;

function OnDownloadProgress(const Url, FileName: String;
  const Progress, ProgressMax: Int64): Boolean;
begin
  Result := Pos('https://', Lowercase(Url)) = 1;
  if not Result then
    Log('Rejected non-HTTPS download URL: ' + Url);
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(
    'PotteryVolumeのダウンロード',
    'アプリケーションをダウンロードしています。', @OnDownloadProgress);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function DownloadSmallFile(const Url, BaseName: String): String;
begin
  if Pos('https://', Lowercase(Url)) <> 1 then
    RaiseException('安全でないダウンロードURLです。');
  DownloadTemporaryFile(Url, BaseName, '', @OnDownloadProgress);
  Result := ExpandConstant('{tmp}\' + BaseName);
end;

function DownloadAndPreparePayload: String;
var
  ReleaseFile: String;
  ChecksumFile: String;
  ReleaseText: AnsiString;
  ChecksumText: AnsiString;
  ExpectedHash: String;
  ChecksumUrl: String;
  ZipUrl: String;
  NewGuiDirectory: String;
begin
  Result := '';
  ReleaseFile := DownloadSmallFile(
    '{#PayloadBaseUrl}/latest/release.txt', 'PotteryVolume-release.txt');
  if not LoadStringFromFile(ReleaseFile, ReleaseText) then
    RaiseException('最新版情報を読み込めませんでした。');
  ReleaseVersion := Lowercase(NormalizeReleaseText(ReleaseText));
  if not IsHexadecimal(ReleaseVersion) or (Length(ReleaseVersion) <> 40) then
    RaiseException('最新版情報のコミットハッシュが不正です。');

  ChecksumUrl := '{#PayloadBaseUrl}/releases/' + ReleaseVersion +
    '/PotteryVolume-GUI-Windows.zip.sha256';
  ChecksumFile := DownloadSmallFile(
    ChecksumUrl, 'PotteryVolume-GUI-' + ReleaseVersion + '.sha256');
  if not LoadStringFromFile(ChecksumFile, ChecksumText) then
    RaiseException('ZIPのSHA-256情報を読み込めませんでした。');
  ExpectedHash := Lowercase(FirstField(ChecksumText));
  if not IsHexadecimal(ExpectedHash) or (Length(ExpectedHash) <> 64) then
    RaiseException('ZIPのSHA-256情報が不正です。');

  ZipUrl := '{#PayloadBaseUrl}/releases/' + ReleaseVersion +
    '/PotteryVolume-GUI-Windows.zip';
  PayloadZip := ExpandConstant('{tmp}\PotteryVolume-GUI-' + ReleaseVersion + '.zip');
  DownloadPage.Clear;
  DownloadPage.Add(ZipUrl, ExtractFileName(PayloadZip), ExpectedHash);
  if not WizardSilent then
    DownloadPage.Show;
  try
    DownloadPage.Download;
    if DownloadPage.AbortedByUser then
      RaiseException('ダウンロードがキャンセルされました。');
  finally
    if not WizardSilent then
      DownloadPage.Hide;
  end;

  StagingRoot := ExpandConstant('{app}\.PotteryVolume-staging');
  if DirExists(StagingRoot) and not DelTree(StagingRoot, True, True, True) then
    RaiseException('前回の一時ファイルを削除できませんでした。');
  if not ForceDirectories(StagingRoot) then
    RaiseException('一時展開先を作成できませんでした。');
  ExtractArchive(PayloadZip, StagingRoot, '', True, nil);
  NewGuiDirectory := StagingRoot + '\PotteryVolume_gui';
  if not FileExists(NewGuiDirectory + '\PotteryVolume_gui.exe') then begin
    DelTree(StagingRoot, True, True, True);
    RaiseException('ZIPにPotteryVolume_gui.exeがありません。');
  end;
  PreparedPayload := True;
  Result := '';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  RetryChoice: Integer;
  ErrorText: String;
begin
  Result := '';
  NeedsRestart := False;
  PreparedPayload := False;
  repeat
    try
      Result := DownloadAndPreparePayload;
      Exit;
    except
      ErrorText := GetExceptionMessage;
      if (StagingRoot <> '') and DirExists(StagingRoot) then
        DelTree(StagingRoot, True, True, True);
      Log('Payload preparation failed: ' + ErrorText);
      if WizardSilent then
        RetryChoice := MsgBox(
          'アプリケーションを準備できませんでした。' + #13#10 + ErrorText + #13#10 + #13#10 + 'ダウンロードを再試行しますか？',
          mbError, MB_RETRYCANCEL);
      if not WizardSilent then
        RetryChoice := SuppressibleMsgBox(
          'アプリケーションを準備できませんでした。' + #13#10 + ErrorText + #13#10 + #13#10 + 'ダウンロードを再試行しますか？',
          mbError, MB_RETRYCANCEL, IDRETRY);
      if RetryChoice = IDRETRY then
        Continue;
      Result := 'PotteryVolumeをインストールできませんでした。ネットワーク接続を確認して、もう一度お試しください。' + #13#10 + ErrorText;
      Exit;
    end;
  until False;
end;

function SwapPreparedPayload: Boolean;
var
  TargetDirectory: String;
  NewGuiDirectory: String;
  BackupDirectory: String;
  HadOldPayload: Boolean;
begin
  Result := False;
  if not PreparedPayload then
    RaiseException('検証済みのアプリケーションがありません。');
  TargetDirectory := ExpandConstant('{app}\PotteryVolume_gui');
  NewGuiDirectory := StagingRoot + '\PotteryVolume_gui';
  BackupDirectory := ExpandConstant('{app}\.PotteryVolume-backup');
  if DirExists(BackupDirectory) and
    not DelTree(BackupDirectory, True, True, True) then
    RaiseException('前回のバックアップを削除できませんでした。');

  HadOldPayload := DirExists(TargetDirectory);
  if HadOldPayload and not RenameFile(TargetDirectory, BackupDirectory) then
    RaiseException('既存アプリケーションをバックアップできませんでした。');
  if not RenameFile(NewGuiDirectory, TargetDirectory) then begin
    if HadOldPayload and not RenameFile(BackupDirectory, TargetDirectory) then
      RaiseException('新しいアプリケーションを配置できず、既存版の復元にも失敗しました。');
    RaiseException('新しいアプリケーションを配置できませんでした。既存版は復元しました。');
  end;

  if HadOldPayload then
    DelTree(BackupDirectory, True, True, True);
  DelTree(StagingRoot, True, True, True);
  PreparedPayload := False;
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
  ErrorText: String;
  AppDirectory: String;
  AppExecutable: String;
begin
  if CurStep = ssInstall then begin
    try
      SwapPreparedPayload;
    except
      ErrorText := GetExceptionMessage;
      Log('Payload replacement failed: ' + ErrorText);
      SuppressibleMsgBox(
        'PotteryVolume の更新に失敗しました。' + #13#10 + ErrorText,
        mbError, MB_OK, IDOK);
      Abort;
    end;
  end;
  if (CurStep = ssDone) and IsUpdateMode then begin
    AppDirectory := ExpandConstant('{app}\PotteryVolume_gui');
    AppExecutable := AppDirectory + '\PotteryVolume_gui.exe';
    if FileExists(AppExecutable) then begin
      if not Exec(AppExecutable, '', AppDirectory, SW_SHOWNORMAL,
        ewNoWait, ErrorCode) then
        Log('Could not start the updated GUI. Error code: ' + IntToStr(ErrorCode));
    end;
  end;
end;

procedure RegisterExtraCloseApplicationsResources;
var
  Executable: String;
  Registered: Boolean;
begin
  Executable := ExpandConstant('{app}\PotteryVolume_gui\PotteryVolume_gui.exe');
  if FileExists(Executable) then begin
    Registered := RegisterExtraCloseApplicationsResource(False, Executable);
    if not Registered then
      Log('Could not register GUI executable with Restart Manager: ' + Executable);
  end;
end;
