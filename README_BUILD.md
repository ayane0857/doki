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

`build-exe` ワークフローは両方の配布フォルダーを `PotteryVolume-Windows-<commit-sha>` というArtifact名でアップロードします。
