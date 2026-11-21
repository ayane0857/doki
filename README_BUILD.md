# ビルド手順

CLI版・GUI版の配布フォルダーと、Windows用セットアップを作成する手順です。

## 要件

- Python 3.12～3.14。WindowsのGitHub ActionsではPython 3.14を使用します。
- Windowsでは `python` と `pip` が使えるようにしてください。
- Windowsセットアップのビルドには Inno Setup 6.5.0 以降が必要です。
- Linux/macOSでは共有ライブラリ付きのPythonが必要です。`build_exe.sh` は `.venv-build` を作成または再利用します。

## 両バージョンをビルドする

リポジトリのルートで、Windowsでは次を実行します。

```powershell
cmd.exe /c build_exe.bat
```

Linux/macOSでは次を実行します。

```bash
bash build_exe.sh
```

スクリプトが開発用依存関係をインストールし、PyInstallerのonedir形式で両方をビルドします。
Windowsではさらに `PotteryVolume-GUI-Windows.zip` とSHA-256ファイルを作成します。

## 出力先

| 種別 | Windows | Linux/macOS |
| --- | --- | --- |
| CLI版 | `dist/PotteryVolume/PotteryVolume.exe` | `dist/PotteryVolume/PotteryVolume` |
| GUI版 | `dist/PotteryVolume_gui/PotteryVolume_gui.exe` | `dist/PotteryVolume_gui/PotteryVolume_gui` |

各フォルダーには版別の使い方を記載した `README.txt`、実行に必要な `_internal` フォルダー、`THIRD_PARTY_LICENSES.txt` が含まれます。配布時はEXE単体ではなく、フォルダー全体を渡してください。

## 個別に手動ビルドする

依存関係をインストールし、リポジトリのルートからspecを実行します。

```powershell
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean PotteryVolume.spec
python -m PyInstaller --noconfirm --clean PotteryVolume_gui.spec
```

`PotteryVolume.spec` は `pottery_volume_cli.py` からコンソール版CLIを作成します。`PotteryVolume_gui.spec` は `pottery_volume_gui.pyw` からウィンドウ版を作成し、GUI・OCR依存関係を収集します。

配布用の説明書の原稿は [docs/cli/README.txt](./docs/cli/README.txt) と [docs/gui/README.txt](./docs/gui/README.txt) です。それぞれのspecが配布フォルダーに `README.txt` として同梱します。

## Windowsセットアップをビルドする

依存関係をインストールし、Inno Setup 6.5.0以降を用意してから、リポジトリのルートで実行します。

```powershell
python -m pip install -r requirements-dev.txt
.\build.ps1
```

`build.ps1` は `pottery_volume_bootstrap.pyw` をPyInstallerの `--onefile --noconsole` で `dist/PotteryVolume.exe` にし、`BOOTSTRAP_VERSION` を実行ファイルへ同梱した後、`ISCC.exe installer\PotteryVolume.iss` で `dist/PotteryVolume-Setup.exe` を作成します。ローカルビルドではGitのコミットハッシュを同梱します。Gitが使えない場合は `dev` になります。

Inno Setup 6.1で `DownloadTemporaryFile` のSHA-256検証と `CreateDownloadPage` が追加されましたが、このインストーラーはそのダウンロード機能を使いません。インストール時の取得・検証・Zip Slip対策・展開は、ランチャーの `--prepare-only` を呼んで共通処理にしています。最小版を6.5.0とするのは、公式の日本語 `Japanese.isl` が同梱される版だからです。通常は追加取得は不要です。別途取得する場合は[公式翻訳ページ](https://jrsoftware.org/inno-setup/translations)から日本語ファイルをダウンロードし、Inno Setupの `Languages` フォルダーへ `Japanese.isl` として保存してください。

ペイロードのダウンロードに失敗するとランチャーが日本語のエラーを表示します。インストールは続行し、ショートカットから次回起動したときに再試行します。

## GitHub Actions

`build-exe` ワークフローでは、Python 3.12～3.14のテストと静的解析がすべて成功してからWindowsの `build` ジョブを実行します。前段が失敗した場合、`build` はスキップされます。成功したビルドはPRを含むすべての実行で `PotteryVolume-Setup.exe` としてArtifactsにアップロードされます。
masterまたは`v*`タグビルドでは、ペイロードのFTP公開に成功した場合、
完全版のZIPとチェックサムをFTPサーバーへ公開します。`v*`タグビルドでは、作成した `PotteryVolume-Setup.exe` を同じタグ名のGitHub Releaseへ添付します。
GUI版の配布フォルダーは `PotteryVolume-GUI-Windows.zip` と
`PotteryVolume-GUI-Windows.zip.sha256` にまとめます。これらを
`https://file.ayane0857.net/app/doki/windows/releases/<commit-sha>/` にアップロードしてください。
両ファイルのアップロード後、同じサーバーの
`https://file.ayane0857.net/app/doki/windows/latest/release.txt` に公開する
`<commit-sha>` を1回更新してください。

GitHub Actionsでは、`FTP_HOST`、`FTP_USERNAME`、`FTP_PASSWORD` を
リポジトリのActions Secretsへ登録すると、masterへのpushまたは手動実行時に
このディレクトリへFTPで自動アップロードします。ポートが21以外の場合は
`FTP_PORT` Secretも登録してください。

ランチャーは起動時に毎回 `latest/release.txt` を確認します。取得できない場合は、インストール時または過去の起動時に成功した `.last-successful-release` の版で起動します。

## 手動テスト

1. クリーンインストールで既定のインストール先を使い、スタートメニューと既定オンのデスクトップショートカットが `PotteryVolume.exe` を指すこと、`payload\<version>\.ready` と `.last-successful-release` が作成されることを確認します。
2. 別ドライブのパス（例: `D:\Apps\PotteryVolume`）を指定し、ランチャーとpayloadがその場所に置かれて起動することを確認します。
3. オンラインで一度起動した後にネットワークを切断し、最後に成功した版が起動することを確認します。新規オフラインインストールでは準備失敗の日本語メッセージが出て、インストール後の起動で再試行することも確認します。
4. 新しいコミットのGUI ZIPと `.sha256` を `/releases/<version>/` に公開してから `/latest/release.txt` を更新し、ランチャー起動時に新しい版が検証・展開されることを確認します。
5. GUIを起動したまま上書きインストールとアンインストールを行い、Restart Managerが対象アプリを検出してファイル操作を完了できることを確認します。
6. 同じSetup.exeを再実行し、既存のインストール先へ上書きされ、ショートカットが重複しないことを確認します。
