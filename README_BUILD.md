# Windows版のビルドと公開

## 構成

```text
PotteryVolume-Setup.exe（Inno Setup、軽量）
  ├─ インストール先・ショートカット・アンインストール
  └─ HTTPSでGUI ZIPを取得 → SHA-256検証 → staging展開 → GUIフォルダーを入れ替え

PotteryVolume_gui.exe（PyInstaller onedir）
  └─ 起動後にバックグラウンドで最新版を確認
       └─ 承認後、検証済みSetup.exeを起動して終了
```

ランチャーや `bootstrap.py` は使いません。SetupとGUIの更新確認はどちらも、従来の配布先 `https://file.ayane0857.net/app/doki/windows` を使います。

## ビルド要件

- Python 3.12～3.14。CIはPython 3.14を使用します。
- WindowsセットアップのコンパイルにはInno Setup 6.5.0以降が必要です。6.5.0でZIPを扱う `ExtractArchive` と `ArchiveExtraction=full` が追加されました。`DownloadTemporaryFile` のSHA-256検証と `CreateDownloadPage` は6.1以降の機能です。
- Inno Setup 6.5.0以降には公式日本語UI `Languages\Japanese.isl` が同梱されています。見つからない場合は[公式翻訳ページ](https://jrsoftware.org/inno-setup/translations)のJapanese「6.5.0+」を保存し、Inno Setupの `Languages` フォルダーに `Japanese.isl` として置いてください。

## ビルド手順

リポジトリのルートで実行します。

```powershell
python -m pip install -r requirements-dev.txt
cmd.exe /c build\build_exe.bat
.\build\build.ps1
```

`build/build_exe.bat` は `build/BUILD_INFO.json` を生成し、CLI版とGUI版をPyInstallerでビルドして、GUIフォルダーをZIP化します。`build/prepare_payload.py` はZIP内の `PotteryVolume_gui/` 構成を保ち、ZIPとSHA-256メタデータを作成します。`build/build.ps1` は同じビルド情報を再生成してから `ISCC.exe` を実行します。Setup の `AppVersion` と GUI のタイトルに表示する版は、`pyproject.toml` の `project.version` から読みます。リリースタグを作成する前に `project.version` を更新してください。タグ名が `v<project.version>` と一致しないと、タグのビルドは失敗します。コミットは `GITHUB_SHA`、`git rev-parse HEAD`、`dev` の順で決め、GUIに `BUILD_INFO.json` として同梱します。

```powershell
ISCC.exe /DAppVersion=0.1.0 /DCommitSha=<40桁のコミットSHA> build\installer\PotteryVolume.iss
```

通常の作業では引数を直接渡す必要はなく、`build/build.ps1` が値を設定します。出力は次のとおりです。

- CLI: `build/dist\PotteryVolume\PotteryVolume.exe`
- GUIフォルダー: `build/dist\PotteryVolume_gui\`
- 配布用GUI ZIP: `build/PotteryVolume-GUI-Windows.zip` と `.sha256`
- インストーラー: `build/dist\PotteryVolume-Setup.exe`

SetupはGUI ZIPを内包しません。Inno Setupのダウンロード機能で `latest/release.txt` とZIPの `.sha256` を取得し、`DownloadTemporaryFile` / `CreateDownloadPage` のSHA-256検証付きダウンロードを行います。インストール先の staging に展開してから `{app}\PotteryVolume_gui` に入れ替えます。入れ替えに失敗したときはバックアップから復元します。

ZIP展開にはInno Setupの `ExtractArchive` を採用しました。6.5.0以降の `ArchiveExtraction=full` はZIPを扱い、公式のセキュリティ説明では外部アーカイブの展開に堅牢なWindowsパス検証を適用して悪意あるパスを防ぐとされています。そのため `tar.exe` / PowerShell展開や独自のZIPパス検査を重ねず、標準の展開処理に任せています。[6.5.0の変更履歴](https://jrsoftware.org/files/is6.5-whatsnew.htm)、[アーカイブ展開](https://jrsoftware.org/inno-setup/documentation/topic_isxfunc_extractarchive.htm)、[セキュリティ対策](https://jrsoftware.org/inno-setup/documentation/topic_securitymeasures.htm)

通常インストールでは「インストール準備完了」画面（`wpReady`）で「インストール」を押すと取得・検証・展開を行います。自動更新では `/SILENT` を検出し、`PrepareToInstall` が進捗ページを開かずに同じ処理を行います。[Inno Setup 公式仕様](https://jrsoftware.org/ishelp/topic_scriptevents.htm)では `/SILENT` でも `NextButtonClick` が呼ばれますが、取得処理は二重に実行しません。失敗すると最大3回試行した後、失敗工程と Setup ログのパスを表示して再試行かキャンセルを選べます。Setup ログの既定の保存先は `%TEMP%` です。

既存GUIの置き換えは取得・検証・staging展開がすべて成功してから行います。更新時はGUIがSetupを `/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /UPDATE=1` 付きで起動し、Inno Setupが前回のインストール先を使います。サイレント時も失敗時の独自エラー・再試行ダイアログは表示します。ZIP取得先の `%TEMP%` と、展開先のインストールドライブには、それぞれダウンロードと展開に必要な空き容量が必要です。取得するリリースは実行時に決まるため、Setupの表示容量にはZIPと展開済みGUIのサイズは含まれません。

GUIは `Local\PotteryVolumeAppMutex` という名前付きmutexを保持します。Inno Setupの `AppMutex` が起動時にこのmutexを確認するため、GUI実行中の上書きインストールとアンインストールを検出できます。インストーラー側では `RegisterExtraCloseApplicationsResources` からGUI実行ファイルもRestart Managerへ登録し、Setupのファイル入れ替え時に使用中プロセスを検出します。

### ZIP 展開先のパス長確認

配布用ZIP（またはビルド後の `PotteryVolume_gui` フォルダー）を指定し、最長の相対パスと `{app}\.PotteryVolume-staging` 配下の最長パスを確認できます。`--app-dir` を省略すると、そのWindowsユーザーの既定のインストール先で計測します。従来の `MAX_PATH`（終端のNULを含む260 UTF-16コード単位）に収まらない場合は終了コード `1` になります。

```powershell
python build\scripts\check_payload_paths.py build\PotteryVolume-GUI-Windows.zip
python build\scripts\check_payload_paths.py build\dist\PotteryVolume_gui --app-dir 'D:\Apps\PotteryVolume'
```

## 起動速度（スプラッシュ）の仕組み

- PyInstaller は Tk を利用できる対応環境でのみ、ブートローダーから `build/splash.png` を表示します。Tk が import できない場合はビルド時に警告を出し、GUI 自体は Qt スプラッシュで起動します。
- GUI は `QApplication` 生成直後に Qt スプラッシュを表示し、ブートローダーのスプラッシュがあれば閉じます。その後、テーマとメインウィンドウを準備し、ウィンドウ表示の約300ミリ秒後に解析ライブラリーを別スレッドで先読みします。`--batch` は Qt を起動せず、CLI を実行します。
- ディスプレイのない Linux で検証する場合は、`QT_QPA_PLATFORM=offscreen` に加えて `PYINSTALLER_SUPPRESS_SPLASH=1` を設定して Tk のウィンドウを無効にします。Tk 付きのビルドでは、デスクトップ上で Tk → Qt → メインウィンドウへ切り替わることを別に確認します。

## 公開ファイルと更新フロー

FTPのHTTPS公開ルートは `https://file.ayane0857.net/app/doki/windows` です。

```text
latest/release.txt
releases/<40桁コミットSHA>/
  PotteryVolume-GUI-Windows.zip
  PotteryVolume-GUI-Windows.zip.sha256
  PotteryVolume-Setup.exe
  PotteryVolume-Setup.exe.sha256
```

GUI起動時は8秒のタイムアウトで `latest/release.txt` を確認します。新版があれば通知し、「今すぐ更新」「後で」「この版をスキップ」を選べます。スキップしたコミットは `QSettings` に保存されます。Setupは別途ストリーミング取得され、同じリリースディレクトリの `.sha256` と照合してから起動します。オフライン等の自動確認失敗はログに記録し、通知を出しません。「更新を確認…」からの手動確認では最新状態または失敗を表示します。ソース実行と `commit=dev` のビルドでは更新確認を行いません。

GitHub ActionsはCLI/GUIをビルド後、ZIP、ZIPのチェックサム、Setup、Setupのチェックサムを同じ `releases/<sha>/` の一時ディレクトリへFTPでアップロードし、ディレクトリ名変更でリリースを公開します。masterビルドだけが `latest/release.txt` を更新します。タグビルドではSetupをGitHub Releaseにも添付します。FTP公開にはActions Secretsの `FTP_HOST`、`FTP_USERNAME`、`FTP_PASSWORD` が必要です。ポートが21以外の場合は `FTP_PORT` も設定します。

## 手動テスト

Windows上で確認してください。

1. **クリーンインストール:** Setupを実行し、インストール先選択、スタートメニュー、既定オンのデスクトップアイコン、通常インストール後の起動を確認します。両ショートカットが `PotteryVolume_gui\PotteryVolume_gui.exe` を指すことを確認します。
2. **別ドライブ:** `D:\Apps\PotteryVolume` などを選び、ZIPの取得とGUI起動がその場所で成功することを確認します。
3. **サイレント更新:** インストール済み状態からSetupを `/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /UPDATE=1` で起動し、GUIファイルを更新してからGUIが自動起動することを確認します。
4. **オフライン時:** GUIを起動したままネットワークを切断します。起動操作が止まらず、更新確認ダイアログが出ないことを確認します。メニューから手動確認した場合は失敗が表示されることも確認します。
5. **更新中の取得失敗・「インストール準備中」の報告を再確認:** ネットワーク遮断、URL不達、ZIPのみ欠落（テスト用配布先で再現）の各条件でSetupを起動します。「インストール準備完了」から「インストール」を押し、「インストール準備中」に進む場合は「次へ」も押します。ダウンロード失敗時にクラッシュせず、該当する工程名と実在する Setup ログのパスが表示されることを確認します。キャンセル時は以前の `PotteryVolume_gui` が残り、`wpReady` から再実行できることを確認します。接続を戻して再試行し、インストール先を変更した場合も古い staging が使われないことを確認します。サイレント更新でも失敗工程が記録されることを確認します。失敗報告にはエラー全文、`%TEMP%` の Setup ログ、使用した Setup.exe の版を添えてください。
6. **ハッシュ不一致:** テスト用リリースでZIPまたはSetupの `.sha256` を不一致にし、拒否されること、展開・起動されないこと、既存GUIが残ることを確認します。
7. **GUI起動中の更新:** GUIを複数起動した状態でSetupを開始し、起動時のAppMutex確認で全GUIを手動終了するよう求められることを確認します。すべて閉じて続行し、更新が正常に完了することを確認します。
8. **Restart Manager:** GUIを閉じた状態でSetupを起動し、起動時のAppMutex確認を通過してからインストール開始前にGUIを起動します。続行後、Restart ManagerがGUIを終了して更新することを別に確認します。
9. **アンインストール:** GUI起動中のアンインストールを確認後、終了して再度アンインストールし、`PotteryVolume_gui` と staging / backup に加え、空になったインストール先（既定は `%LOCALAPPDATA%\Programs\PotteryVolume`）が削除されることを確認します。別のテストではインストール先の直下に任意のファイルを置き、アンインストール後もそのファイルとフォルダーが残ることを確認します。親の `Programs` フォルダーは削除しません。
10. **上書きインストール:** 既定のインストール先を変えずにSetupを再実行し、前回のアプリディレクトリとショートカットが維持されて更新されることを確認します。
11. **通知設定:** 「起動時に更新を確認する」をオフにして再起動し自動確認されないこと、再びオンにすると確認されること、スキップしたコミットが自動通知されず手動確認では表示されることを確認します。

## 自動テストと品質チェック

```powershell
python -m pytest -q
python -m ruff check .
python -m pyright
python -m mypy
```
