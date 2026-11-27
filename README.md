# 土器断面図の体積推定

白背景・黒線の土器実測図から回転軸と右側断面を自動検出し、回転体として容量と器壁体積を推定する Python CLI です。画像全体のスケールや器壁の塗りつぶしは不要です。低解像度の線画でも動かせるようにしていますが、自動検出結果は --debug-dir の重ね合わせ画像で確認してください。

## かんたんに使う

Windows では `python src/pottery_volume_gui.pyw`（または `python src/pottery_volume.py`）を実行すると設定画面が開きます。画像を選び、スケール方法や必要な補正値を設定して「計算する」を押してください。

画面上部の「表示」メニューから「自動（システム設定）・ライト・ダーク」を選べます。自動ではOSの配色設定に合わせて切り替わり、設定は次回起動時にも引き継がれます。

### 土器と目盛りの2枚同時ドロップ（自動判別＆スケール自動解析）
エクスプローラーから**土器の実測図画像**と**目盛り（スケール）画像**の2ファイルをまとめて設定画面へドラッグ＆ドロップすると、OCR・線形状・アスペクト比から画像を振り分けます。目盛り画像のOCRラベルと線候補が十分に一致した場合だけスケール設定へ自動入力します。候補が曖昧な場合は既存の設定を変えず、確認画面で手動選択できます。

### Excelへの貼り付けに特化したコピー機能
計算結果の表示エリア下にあるボタンから、Excelへ貼り付けやすいタブ区切り（TSV）形式でクリップボードにコピーできます。Excel上でセルを選択して `Ctrl + V` を押すだけで、列・行に綺麗に分割して貼り付けられます。
- **Excel用 (横1行)**: データベース・一覧表の作成用（データ行のみ）。
- **Excel用 (ヘッダー付1行)**: 表の先頭行作成用（項目名ヘッダー行 ＋ データ行）。
- **Excel用 (縦の表)**: 単票・個票記録用（「項目」「値」「単位」の縦並び表）。
- **サマリー**: テキストでの報告やメモ用。

### スケールと輪郭の手動調整
- 「画像から自動設定…」でOCRラベルと線候補を読み取り、「目盛りを確認・手動修正…」で画像を開きます。候補線を選ぶ、線上をクリックして選ぶ、端点をドラッグして微調整する操作に対応しています。
- マウスホイールで拡大縮小、右ドラッグで画像を移動できます。線候補が見つからない場合は、画像上で両端をクリックし、読み取った長さまたは実寸を入力してください。
- 計算後に「輪郭を手動補正」を押すと、元画像に内面・外面の輪郭を重ねて表示します。既存点をドラッグするほか、内面または外面を選んで画像を複数回クリックし、任意の高さに補正点を追加できます。右側の表でも編集でき、点の間は補間して体積を再計算します。半径は px 単位です。
- 「ノイズ除去後の画像を表示」で解析時の設定で二値化・ノイズ除去した画像に切り替え、「ノイズ除去前の画像に戻す」で元画像に戻せます。表示の切り替えは計算結果に影響しません。
- 白い破線をドラッグして回転軸を移動できます。「自動輪郭を生成」は現在の軸で輪郭を再抽出し、手動補正を置き換えます。直前の操作は Ctrl+Z で取り消せます。

~~~powershell
python src/pottery_volume.py
~~~

画像を CMD にドラッグしてパスを自動入力する方法:

1. CMD を開き、プロジェクトのフォルダーへ移動します。
2. 次のように入力し、末尾の空白を残します。

~~~text
python src/pottery_volume.py 
~~~

3. エクスプローラーから画像ファイルを CMD にドラッグします。画像のパスが入力されます。
4. 必要なら続けてオプションを入力し、Enter を押します。

~~~text
python src/pottery_volume.py "C:\画像の場所\input.png" --scale-mm-per-px 0.5 --debug-dir out
~~~

スケールを省略すると px 単位で計算します。設定画面では入力欄が用意されているため、コマンドのオプションを覚える必要はありません。

## セットアップ

Python 3.14 を使って動作確認しています。GUIはPySide6を使用します。

~~~powershell
python -m pip install -r requirements.txt
~~~

PySide6のQtランタイムも依存関係に含まれるため、GUIを使う場合は必ずこのセットアップを実行してください。

テストと EXE 作成に必要な開発ツールも入れる場合:

~~~powershell
python -m pip install -r requirements-dev.txt
~~~

主なライブラリはバージョンを固定しています。利用版は NumPy 2.5.4、OpenCV 5.0.0.93、scikit-image 0.26.0、SciPy 1.18.1、Matplotlib 3.11.2 です。

## Windows EXE の作成

Windows では `build\build_exe.bat` でCLI版・GUI版と配布用ペイロードを作成し、`build\build.ps1` で `build\dist\PotteryVolume-Setup.exe` をビルドします。セットアップとビルド手順は [README_BUILD.md](./README_BUILD.md) を参照してください。

セットアップはユーザー単位でGUI本体を直接ダウンロードしてインストールします。GUIは起動時にバックグラウンドで更新を確認し、新版があるときは更新するか選べます。更新設定とスキップした版は「表示」メニューから管理できます。

~~~text
build/dist\PotteryVolume\PotteryVolume.exe
build/dist\PotteryVolume_gui\PotteryVolume_gui.exe
~~~

各配布フォルダーには版ごとの使い方を記した `README.txt` が入ります。ビルド担当者向けの手順は [README_BUILD.md](./README_BUILD.md) を参照してください。

CLI版はコンソールアプリ、GUI版はウィンドウアプリです。GUI版にはランタイムライブラリと OCR モデルが含まれるため、実行先 PC に Python をインストールする必要はありません。

Linux/macOS では `build/build_exe.sh` を実行すると、同じ設定でアプリフォルダーを作成できます。
スクリプトは共有ライブラリ付きPythonからビルド用のvenvを作成して使用します。

配布フォルダーには `THIRD_PARTY_LICENSES.txt` を同梱します。GUIの
「ライセンス表記」ボタンからも表示できます。

~~~bash
bash build/build_exe.sh
~~~

~~~text
build/dist/PotteryVolume/PotteryVolume
build/dist/PotteryVolume_gui/PotteryVolume_gui
~~~

GitHub Actions は Pull Request、`master` への push、`v*` タグの push でテストと静的解析を行い、Windows用Setupを `PotteryVolume-Setup` Artifactとして保存します。`master` への push では更新用の rolling Release `latest` を更新し、`v*` タグの push ではタグ名のGitHub ReleaseにSetup・GUI ZIPとSHA-256ファイルを添付します。

### バージョン付きリリース

`pyproject.toml` の `project.version` とタグ名を一致させます。たとえば `0.1.7` をリリースする場合は、まず `project.version` を `0.1.7` に変更し、その変更を `master` にコミットしてからタグを push します。一致しないタグ（`v0.1.7` と `project.version = "0.1.6"` など）はビルドに失敗します。

```powershell
# pyproject.toml の project.version を 0.1.7 に変更した後
git add pyproject.toml
git commit -m "Bump version to 0.1.7"
git push origin master

# master に push したコミットにタグを付けて公開
git tag -a v0.1.7 -m "Release v0.1.7"
git push origin v0.1.7
```

タグの push で GitHub Actions がテスト・静的解析・Windowsビルドを実行します。成功すると `v0.1.7` のGitHub Releaseが作成され、Setup、GUI ZIP、各SHA-256ファイルが添付されます。Actionsの実行結果とGitHub Releasesで公開状況を確認してください。現在のWorkflowはタグ付きReleaseをプレリリースとして作成します。

CLI版はGUIを開かずに画像を処理します。JSON が必要な場合だけ --json-out を指定してください。

~~~text
build\dist\PotteryVolume\PotteryVolume.exe input.png --scale-mm-per-px 0.5 --json-out result.json --debug-dir out
~~~

## 実行

mm/px を直接指定する例:

~~~powershell
python src/pottery_volume.py input.png --scale-mm-per-px 0.5 --debug-dir out
~~~

画像内の既知距離が 100 px = 50 mm の場合:

~~~powershell
python src/pottery_volume.py input.png --scale-bar-px 100 --scale-bar-mm 50 --debug-dir out
~~~

2点の座標から画像上の距離を求める場合:

~~~powershell
python src/pottery_volume.py input.png --scale-points 40,20,140,20 --scale-bar-mm 50
~~~

器高の実寸からスケールを逆算する場合:

~~~powershell
python src/pottery_volume.py input.png --vessel-height-mm 120
~~~

スケールを指定しない場合は警告を出し、長さを px、体積を px³ として出力します。JSON は既定では保存せず、--json-out path.json を指定した場合だけ保存します。スケールを指定した結果には mm³、cm³、mL を出力します（1 cm³ = 1 mL）。

## 自動検出と上書き

1. PNG の透明部分は白い背景に合成し、EXIF の向きを反映してから Otsu 二値化を行います。前景量が極端な場合または --adaptive-threshold 指定時は適応的二値化に切り替えます。
2. 小さい連結成分を除去し、中央付近の垂直投影から長い線を回転軸として検出します。
3. 軸の右側を切り出して --closing-kernel の形態学クロージングを行います。外側背景を flood fill で塗り、最大の閉領域を器壁断面として使います。閉領域を得られない画像では輪郭線追跡モードへ切り替えます。--profile-mode lines で内面線・外面線追跡を指定できます。
4. 各行の最小・最大 x 座標から内面半径と外面半径を取り、短い欠損を補間します。Savitzky–Golay 平滑化の既定窓は 5 px です。
5. 液面から底まで円板積分で容量と器壁体積を求めます。断面マスクの面積・重心を使うパップス・ギュルダンの定理でも器壁体積を計算し、差を検算値として表示します。

自動検出がずれた場合は軸・切り出し・液面を px 単位で指定できます。

~~~powershell
python src/pottery_volume.py input.png --axis-x 135 --crop 135,20,260,240 --liquid-level-y 48
~~~

主なオプション:

| オプション | 説明 |
| --- | --- |
| --axis-x X | 回転軸 x 座標を手動指定 |
| --crop x0,y0,x1,y1 | 断面を探す領域を指定。軸右側に器壁が含まれるようにする |
| --liquid-level-y Y | 満水位を画像 y 座標で指定。省略時は検出した口縁の最上行 |
| --closing-kernel N | 断線を閉じるカーネルサイズ。大きくしすぎると細部が消えるため、デバッグ画像で調整 |
| --profile-mode MODE | auto、filled、lines から断面抽出方式を指定 |
| --min-component-area N | 二値化後に除去する小連結成分のしきい値 |
| --smooth-window N | プロファイル平滑化窓（奇数）。0 で無効 |
| --debug-dir DIR | detection_overlay.png、section_closed.png、section_mask.png、profiles.png を保存 |

### 画像上のスケール表記を使う

GUIの「画像から自動設定…」は、OCRから mm、cm、m 表記と数値を読み、文字領域を線候補から除外します。線の濃さと連続性、端の目盛り、OCRラベルとの距離を使って候補を並べ、OCRと線の信頼度が低い場合や複数候補が残る場合は自動適用しません。たとえば「10cm」の線が 436 px なら 100 mm ÷ 436 px = 約 0.22936 mm/px です。「目盛りを確認・手動修正…」で候補の選択、ズーム、端点ドラッグ、手動指定ができます。

## 出力の見方

- 器高、口径、最大径は検出した軸から片側断面までを回転対称として算出します。
- 満水容量は内面輪郭の最上行から底までです。--liquid-level-y はこれより低い液面にできます。
- 器壁体積は各行の π (r_out² − r_in²) Δy を積算します。
- パップス検算の差が大きい場合は、断面抽出、軸、切り出し範囲、閉領域の選択をデバッグ画像で確認してください。軸対称でない器形や遠近歪みのある写真は誤差が大きくなります。
- JSON には単位、検出範囲、軸、断面抽出モード、警告も含めます。

## ソースコードの構成

`src/` 直下には実行用スクリプトだけを置き、実装を [`doki` パッケージ](./src/doki/) にまとめています。既存の起動コマンドはそのまま使えます。Python から利用する場合は `doki.api` から解析関数を import してください。インストール後は `python -m doki.cli` でも CLI を起動できます。

- [`analysis/`](./src/doki/analysis/) — 画像処理、輪郭抽出、体積計算、解析フロー、可視化。
- [`scale/`](./src/doki/scale/) — スケール校正、OCR、目盛り線検出、候補の照合。
- [`gui/`](./src/doki/gui/) — GUI の起動、編集ダイアログ、キャンバス、バックグラウンド処理。[`gui/window/`](./src/doki/gui/window/) にメインウィンドウの画面構築、入力、解析、結果、履歴、更新を分けています。

## テスト

~~~powershell
python -m pytest -q
~~~

テストは円筒殻と半球殻の合成線画を処理し、容量・器壁体積の解析値との誤差 5% 以内、ならびにスケール換算を確認します。

## Python、品質チェック、PyInstaller

`pyproject.toml` に実行時依存と対応Pythonバージョン（CPython 3.14）を定義しています。開発用依存には Ruff、Pyright、pytest、PyInstaller を含めています。

~~~powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
pyright
~~~

`build/` 内の `.spec` はプロジェクトのルートから実行します。`build/PotteryVolume.spec` はコンソール形式のCLI版 `build/dist/PotteryVolume/PotteryVolume.exe`、`build/PotteryVolume_gui.spec` はウィンドウ形式のGUI版 `build/dist/PotteryVolume_gui/PotteryVolume_gui.exe` を作ります。GUI版はRapidOCRとPySide6のデータ・バイナリ・hidden importを収集します。両方に `THIRD_PARTY_LICENSES.txt` を同梱します。

~~~powershell
python -m PyInstaller --noconfirm --workpath build/work --distpath build/dist build/PotteryVolume.spec
python -m PyInstaller --noconfirm --workpath build/work --distpath build/dist build/PotteryVolume_gui.spec
~~~

`build/build_exe.bat` と `build/build_exe.sh` はCLI版とGUI版の両方を作ります。
