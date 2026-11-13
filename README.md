# 土器断面図の体積推定

白背景・黒線の土器実測図から回転軸と右側断面を自動検出し、回転体として容量と器壁体積を推定する Python CLI です。画像全体のスケールや器壁の塗りつぶしは不要です。低解像度の線画でも動かせるようにしていますが、自動検出結果は --debug-dir の重ね合わせ画像で確認してください。

## かんたんに使う

Windows では `pottery_volume_gui.pyw`（または `pottery_volume.py`）を実行すると設定画面が開きます。画像を選び、スケール方法や必要な補正値を設定して「計算する」を押してください。

### 土器と目盛りの2枚同時ドロップ（自動判別＆スケール自動解析）
エクスプローラーから**土器の実測図画像**と**目盛り（スケール）画像**の2ファイルをまとめて設定画面へドラッグ＆ドロップすると、AI（OCR・スケールバー・アスペクト比解析）が自動で「土器は土器」「目盛りは目盛り」に振り分けます。さらに目盛り画像から長さ（例: `10cm`）とピクセル数を自動解析し、スケール設定に自動入力します。

### Excelへの貼り付けに特化したコピー機能
計算結果の表示エリア下にあるボタンから、Excelへ貼り付けやすいタブ区切り（TSV）形式でクリップボードにコピーできます。Excel上でセルを選択して `Ctrl + V` を押すだけで、列・行に綺麗に分割して貼り付けられます。
- **Excel用 (横1行)**: データベース・一覧表の作成用（データ行のみ）。
- **Excel用 (ヘッダー付1行)**: 表の先頭行作成用（項目名ヘッダー行 ＋ データ行）。
- **Excel用 (縦の表)**: 単票・個票記録用（「項目」「値」「単位」の縦並び表）。
- **サマリー**: テキストでの報告やメモ用。

### スケールの手動調整・測定
- スケールを画像上で測るには、「画像上で測定…」を押してください（目盛り画像が指定されている場合は目盛り画像が開きます）。画像上で2点をクリックして実寸 mm を入力すると反映されます。
- OCRで読み取るには、「画像から自動設定…」を押してください。OCRが「10cm」「50 mm」「1m」などの距離と単位を読み、目盛り線を自動検出します。

~~~powershell
python pottery_volume.py
~~~

画像を CMD にドラッグしてパスを自動入力する方法:

1. CMD を開き、プロジェクトのフォルダーへ移動します。
2. 次のように入力し、末尾の空白を残します。

~~~text
python pottery_volume.py 
~~~

3. エクスプローラーから画像ファイルを CMD にドラッグします。画像のパスが入力されます。
4. 必要なら続けてオプションを入力し、Enter を押します。

~~~text
python pottery_volume.py "C:\画像の場所\input.png" --scale-mm-per-px 0.5 --debug-dir out
~~~

スケールを省略すると px 単位で計算します。設定画面では入力欄が用意されているため、コマンドのオプションを覚える必要はありません。

## セットアップ

Python 3.14 を使って動作確認しています。Tkinter は Python 標準ライブラリです。

~~~powershell
python -m pip install -r requirements.txt
~~~

テストと EXE 作成に必要な開発ツールも入れる場合:

~~~powershell
python -m pip install -r requirements-dev.txt
~~~

主なライブラリはバージョンを固定しています。利用版は NumPy 2.5.4、OpenCV 5.0.0.93、scikit-image 0.26.0、SciPy 1.18.1、Matplotlib 3.11.2 です。

## Windows EXE の作成

Windows では `build_exe.bat` を実行するとアプリフォルダーが作成されます。配布する際は EXE と `_internal` フォルダーを一緒に配置してください。

~~~text
dist\PotteryVolume_ScaleOCR\PotteryVolume_ScaleOCR.exe
~~~

アプリフォルダーにはランタイムライブラリと OCR モデルが含まれるため、実行先 PC に Python をインストールする必要はありません。

Linux/macOS では `build_exe.sh` を実行すると、同じ設定でアプリフォルダーを作成できます。
スクリプトは共有ライブラリ付きPythonからビルド用のvenvを作成して使用します。

~~~bash
bash build_exe.sh
~~~

~~~text
dist/PotteryVolume_ScaleOCR/PotteryVolume_ScaleOCR
~~~

GitHub Actions ではコミットごとにWindows版をビルドし、ZIPをArtifactとして保存します。GitHubのActionsから対象の実行結果を開き、Artifactsの `PotteryVolume_ScaleOCR-<commit-sha>` をダウンロードしてください。

CMD からGUIを開かずに実行する場合は --batch を付けます。JSON が必要な場合だけ --json-out を指定してください。

~~~text
dist\PotteryVolume_ScaleOCR\PotteryVolume_ScaleOCR.exe --batch input.png --scale-mm-per-px 0.5 --json-out result.json --debug-dir out
~~~

## 実行

mm/px を直接指定する例:

~~~powershell
python pottery_volume.py input.png --scale-mm-per-px 0.5 --debug-dir out
~~~

画像内の既知距離が 100 px = 50 mm の場合:

~~~powershell
python pottery_volume.py input.png --scale-bar-px 100 --scale-bar-mm 50 --debug-dir out
~~~

2点の座標から画像上の距離を求める場合:

~~~powershell
python pottery_volume.py input.png --scale-points 40,20,140,20 --scale-bar-mm 50
~~~

器高の実寸からスケールを逆算する場合:

~~~powershell
python pottery_volume.py input.png --vessel-height-mm 120
~~~

スケールを指定しない場合は警告を出し、長さを px、体積を px³ として出力します。JSON は既定では保存せず、--json-out path.json を指定した場合だけ保存します。スケールを指定した結果には mm³、cm³、mL を出力します（1 cm³ = 1 mL）。

## 自動検出と上書き

1. Otsu 二値化を行い、前景量が極端な場合または --adaptive-threshold 指定時は適応的二値化に切り替えます。
2. 小さい連結成分を除去し、中央付近の垂直投影から長い線を回転軸として検出します。
3. 軸の右側を切り出して --closing-kernel の形態学クロージングを行います。外側背景を flood fill で塗り、最大の閉領域を器壁断面として使います。閉領域を得られない画像では輪郭線追跡モードへ切り替えます。--profile-mode lines で内面線・外面線追跡を指定できます。
4. 各行の最小・最大 x 座標から内面半径と外面半径を取り、短い欠損を補間します。Savitzky–Golay 平滑化の既定窓は 5 px です。
5. 液面から底まで円板積分で容量と器壁体積を求めます。断面マスクの面積・重心を使うパップス・ギュルダンの定理でも器壁体積を計算し、差を検算値として表示します。

自動検出がずれた場合は軸・切り出し・液面を px 単位で指定できます。

~~~powershell
python pottery_volume.py input.png --axis-x 135 --crop 135,20,260,240 --liquid-level-y 48
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

GUIの「画像から自動設定…」は、OCRから mm、cm、m 表記と数値を読み、目盛り線の候補を画像から検出します。たとえば「10cm」の線が 436 px なら 100 mm ÷ 436 px = 約 0.22936 mm/px として設定します。認識した値・単位と線の両端を画面で確認してから反映してください。表記が読めない画像でも、距離と単位の手入力および線の両端クリックで設定できます。

## 出力の見方

- 器高、口径、最大径は検出した軸から片側断面までを回転対称として算出します。
- 満水容量は内面輪郭の最上行から底までです。--liquid-level-y はこれより低い液面にできます。
- 器壁体積は各行の π (r_out² − r_in²) Δy を積算します。
- パップス検算の差が大きい場合は、断面抽出、軸、切り出し範囲、閉領域の選択をデバッグ画像で確認してください。軸対称でない器形や遠近歪みのある写真は誤差が大きくなります。
- JSON には単位、検出範囲、軸、断面抽出モード、警告も含めます。

## テスト

~~~powershell
python -m pytest -q
~~~

テストは円筒殻と半球殻の合成線画を処理し、容量・器壁体積の解析値との誤差 5% 以内、ならびにスケール換算を確認します。
