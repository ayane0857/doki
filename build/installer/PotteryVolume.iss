; PotteryVolume GUI installer. The GUI payload is downloaded at install time.

#ifndef AppVersion
  #error AppVersion must be supplied by build.ps1
#endif
#ifndef CommitSha
  #error CommitSha must be supplied by build.ps1
#endif
#ifndef JapaneseLanguageFile
  #error JapaneseLanguageFile must be supplied by build.ps1
#endif

#define PayloadBaseUrl "https://github.com/ayane0857/doki/releases/download/latest"

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
Name: "japanese"; MessagesFile: "{#JapaneseLanguageFile}"

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
Type: dirifempty; Name: "{app}"

[Code]
var
  DownloadPage: TDownloadWizardPage;
  StagingRoot: String;
  PreparedPayload: Boolean;
  UserCancelledDownload: Boolean;
  PayloadReplaced: Boolean;

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

procedure RemoveTemporaryDownload(const FileName: String);
begin
  if FileExists(FileName) and not DeleteFile(FileName) then
    RaiseException('一時ダウンロードを削除できませんでした: ' + FileName);
end;

function DownloadSmallFile(const Url, BaseName: String): String;
begin
  if Pos('https://', Lowercase(Url)) <> 1 then
    RaiseException('安全でないダウンロードURLです。');
  Result := ExpandConstant('{tmp}\' + BaseName);
  RemoveTemporaryDownload(Result);
  if DownloadTemporaryFile(Url, BaseName, '', @OnDownloadProgress) <= 0 then
    RaiseException('取得したファイルが空です: ' + BaseName);
end;

procedure SetPayloadStage(var Stage: String; const Name, Detail: String);
begin
  Stage := Name;
  Log('Payload stage: ' + Stage + ' - ' + Detail);
end;

function PayloadError(const Stage, Detail: String): String;
var
  LogPath: String;
begin
  LogPath := ExpandConstant('{log}');
  if LogPath = '' then
    LogPath := ExpandConstant('{%TEMP}');
  Result := 'PotteryVolumeの準備に失敗しました。' + #13#10 + '工程: ' + Stage;
  if Trim(Detail) <> '' then
    Result := Result + #13#10 + Detail;
  Result := Result + #13#10 + 'Setup ログ: ' + LogPath;
end;

procedure CleanStaging;
begin
  PreparedPayload := False;
  if StagingRoot = '' then
    Exit;
  if DirExists(StagingRoot) and not DelTree(StagingRoot, True, True, True) then
    Log('Could not remove staging directory: ' + StagingRoot)
  else
    StagingRoot := '';
end;

procedure DownloadAndPreparePayload(var Stage: String);
var
  ChecksumFile: String;
  ChecksumText: AnsiString;
  ExpectedHash: String;
  ChecksumUrl: String;
  ZipUrl: String;
  ZipBaseName: String;
  PayloadZip: String;
  NewStagingRoot: String;
  NewGuiDirectory: String;
  BytesDownloaded: Int64;
begin
  ChecksumUrl := '{#PayloadBaseUrl}/PotteryVolume-GUI-Windows.zip.sha256';
  SetPayloadStage(Stage, '.sha256 の取得', ChecksumUrl);
  ChecksumFile := DownloadSmallFile(
    ChecksumUrl, 'PotteryVolume-GUI-Windows.zip.sha256');
  if not LoadStringFromFile(ChecksumFile, ChecksumText) then
    RaiseException('ZIPのSHA-256情報を読み込めませんでした。');
  ExpectedHash := Lowercase(FirstField(ChecksumText));
  if not IsHexadecimal(ExpectedHash) or (Length(ExpectedHash) <> 64) then
    RaiseException('ZIPのSHA-256情報が不正です。');

  ZipUrl := '{#PayloadBaseUrl}/PotteryVolume-GUI-Windows.zip';
  ZipBaseName := 'PotteryVolume-GUI.zip';
  SetPayloadStage(Stage, 'ZIP の取得・SHA-256 検証', ZipUrl);
  PayloadZip := ExpandConstant('{tmp}\' + ZipBaseName);
  RemoveTemporaryDownload(PayloadZip);
  if WizardSilent then
    BytesDownloaded := DownloadTemporaryFile(ZipUrl, ZipBaseName, ExpectedHash, @OnDownloadProgress)
  else begin
    DownloadPage.Clear;
    DownloadPage.Add(ZipUrl, ZipBaseName, ExpectedHash);
    DownloadPage.Show;
    try
      BytesDownloaded := DownloadPage.Download;
    finally
      UserCancelledDownload := DownloadPage.AbortedByUser;
      DownloadPage.Hide;
    end;
    if UserCancelledDownload then
      RaiseException('ダウンロードがキャンセルされました。');
  end;
  Log('Verified ZIP download bytes: ' + IntToStr(BytesDownloaded));

  NewStagingRoot := ExpandConstant('{app}\.PotteryVolume-staging');
  SetPayloadStage(Stage, 'staging の作成', NewStagingRoot);
  if (StagingRoot <> '') and (CompareText(StagingRoot, NewStagingRoot) <> 0) then
    RaiseException('以前の一時展開先を削除できませんでした: ' + StagingRoot);
  StagingRoot := NewStagingRoot;
  if DirExists(StagingRoot) and not DelTree(StagingRoot, True, True, True) then
    RaiseException('前回の一時ファイルを削除できませんでした。');
  if not ForceDirectories(StagingRoot) then
    RaiseException('一時展開先を作成できませんでした。');
  SetPayloadStage(Stage, 'ZIP の展開', PayloadZip + ' -> ' + StagingRoot);
  ExtractArchive(PayloadZip, StagingRoot, '', True, nil);
  NewGuiDirectory := StagingRoot + '\PotteryVolume_gui';
  SetPayloadStage(Stage, 'EXE の存在確認', NewGuiDirectory + '\PotteryVolume_gui.exe');
  if not FileExists(NewGuiDirectory + '\PotteryVolume_gui.exe') then
    RaiseException('ZIPにPotteryVolume_gui.exeがありません。');
  PreparedPayload := True;
  Log('Payload preparation complete.');
end;

function HasPreparedPayload: Boolean;
begin
  Result := PreparedPayload and
    (CompareText(StagingRoot, ExpandConstant('{app}\.PotteryVolume-staging')) = 0) and
    FileExists(StagingRoot + '\PotteryVolume_gui\PotteryVolume_gui.exe');
end;

function PreparePayload: String;
var
  Attempt: Integer;
  RetryChoice: Integer;
  Stage: String;
  ErrorText: String;
begin
  Result := '';
  if HasPreparedPayload then
    Exit;
  CleanStaging;
  repeat
    for Attempt := 1 to 3 do begin
      Stage := '準備の開始';
      UserCancelledDownload := False;
      Log(Format('Payload preparation attempt %d of 3', [Attempt]));
      try
        DownloadAndPreparePayload(Stage);
        Result := '';
        Exit;
      except
        ErrorText := GetExceptionMessage;
        if UserCancelledDownload then
          ErrorText := 'ダウンロードがキャンセルされました。';
        Result := PayloadError(Stage, ErrorText);
        Log('Payload preparation failed: ' + Result);
        CleanStaging;
      end;
      if UserCancelledDownload then
        Exit;
    end;
    RetryChoice := MsgBox(Result + #13#10#13#10 + '準備を再試行しますか？',
      mbError, MB_RETRYCANCEL);
  until RetryChoice <> IDRETRY;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and not WizardSilent then
    Result := PreparePayload = '';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  NeedsRestart := False;
  Result := '';
  if WizardSilent then
    Result := PreparePayload
  else if not HasPreparedPayload then begin
    Result := PayloadError('EXE の存在確認', '準備済みのアプリケーションがありません。');
    Log(Result);
  end;
end;

procedure DeinitializeSetup;
begin
  CleanStaging;
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

  if HadOldPayload and not DelTree(BackupDirectory, True, True, True) then
    Log('Could not remove backup directory: ' + BackupDirectory);
  CleanStaging;
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
    PayloadReplaced := False;
    try
      if not SwapPreparedPayload then
        RaiseException('アプリケーションの配置に失敗しました。');
      PayloadReplaced := True;
    except
      ErrorText := GetExceptionMessage;
      Log('Payload replacement failed: ' + ErrorText);
      if SuppressibleMsgBox(
        'PotteryVolume の更新に失敗しました。' + #13#10 + ErrorText,
        mbError, MB_OK, IDOK) <> IDOK then
        Log('Unexpected response to payload replacement error.');
      Abort;
    end;
  end;
  if (CurStep = ssDone) and IsUpdateMode and PayloadReplaced then begin
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
