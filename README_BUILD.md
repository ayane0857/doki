# ビルド手順

CLI版とGUI版の配布フォルダーを作成する手順です。

## 要件

- Python 3.12～3.14。WindowsのGitHub ActionsではPython 3.14を使用します。
- Windowsでは `python` と `pip` が使えるようにしてください。
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

## GitHub Actions

`build-exe` ワークフローでは、Python 3.12～3.14 のテストと静的解析がすべて成功してから Windows の `build` ジョブを実行します。前段が失敗した場合、`build` は失敗ではなくスキップになります。PRビルドでは配布ファイルをアップロードせず、ビルドとテストだけを実行します。
masterまたは`v*`タグビルドでは、ペイロードのFTP公開に成功した場合、
完全版のZIPとチェックサムをFTPサーバーへのみ公開します。
`PotteryVolume_bootstrap.exe` と `pottery_volume_bootstrap.py` は
`v*`タグビルドでのみGitHub Releaseへ添付し、タグ名のReleaseを使用します。
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

ローカルで `build_exe.bat` を実行した場合は `BOOTSTRAP_VERSION` が `dev`
になり、公開済みの最新ペイロードを使用します。ローカル生成したZIPを
公開URLへ手動でアップロードしなければ、そのコミット向けの公開ペイロードには
なりません。
