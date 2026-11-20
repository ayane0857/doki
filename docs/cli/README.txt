土器体積推定 CLI版 - 使い方
===========================

CLI版はコマンドプロンプトまたはPowerShellから画像を解析します。GUI画面は開きません。
配布時は PotteryVolume.exe と _internal フォルダーを同じフォルダーに置いてください。

■ 基本の使い方

PowerShellで次のように実行します。画像パスは実際の場所に置き換えてください。

  .\PotteryVolume.exe "C:\data\pottery.png" --scale-mm-per-px 0.13

画像のスケールが分からない場合は、スケールを指定せずに実行できます。その場合、
長さは px、体積は px³ で表示されます。

■ スケールの指定方法

・mm/px が分かる場合:
  --scale-mm-per-px 0.13

・画像上のスケール線の長さと実寸が分かる場合:
  --scale-bar-px 436 --scale-bar-mm 100

・既知の長さの両端座標と実寸が分かる場合:
  --scale-points 40,20,140,20 --scale-bar-mm 50

・土器の器高の実寸が分かる場合:
  --vessel-height-mm 120

スケールの指定は一つの方法を選んでください。詳しいオプションは次のコマンドで確認できます。

  .\PotteryVolume.exe --help

■ 検出結果の確認と保存

--debug-dir を付けると、検出輪郭や断面マスクなどの確認画像を保存します。
--json-out を付けると、解析結果をJSONで保存します。

  .\PotteryVolume.exe "C:\data\pottery.png" --scale-mm-per-px 0.13 --debug-dir ".\debug" --json-out ".\result.json"

自動検出の結果は、debugフォルダーの重ね合わせ画像で確認してください。回転軸や切り出し範囲を
調整したい場合は --axis-x、--crop などを指定できます。詳細は --help を参照してください。

■ 注意

このツールは土器断面を回転対称と仮定して体積を推定します。実際の形状や図面の状態により、
結果に誤差が生じます。警告が出た場合や輪郭が不自然な場合は、検出画像を確認してください。

GUIで操作する場合は PotteryVolume_gui.exe を起動してください。
