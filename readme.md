# Blender 5.2 Rendering

Blender 5.2 の Cycles で、INI 設定に従ってオブジェクトのレンダー画像と形状データを一括生成するスクリプトです。旧版の手動ビルドやコンポジターのソース改変は必要ありません。

## 実行環境

- Blender 5.2 以降
- NumPy（Blender に同梱）
- `misc\viewnpy.py` と `working_dir\visualization.py` は外部 Python で実行する場合に NumPy と Matplotlib が必要です。
- 通常のレンダーは CPU で実行します。GPU を使う場合は Cycles 対応デバイスとドライバーを用意し、設定で `device = GPU` を指定してください。

## 実行

プロジェクトのルートから Blender を起動します。Windows では補助ランチャーを使うと、PATH または標準的なインストール先から Blender を自動で探します。PATH を恒久変更する必要はありません。
PowerShell では `run_blender.ps1`、コマンドプロンプトでは `run_blender.cmd` を使います。

```powershell
.\run_blender.ps1 config_samples\bunny_monochrome.ini
```

```bat
run_blender.cmd config_samples\bunny_monochrome.ini
```

Blender から設定を読み込めるかだけ確認する場合は `-ValidateOnly` を付けます。

```powershell
.\run_blender.ps1 config_samples\bunny_monochrome.ini -ValidateOnly
```

複数の設定ファイルを連続して実行できます。

```powershell
.\run_blender.ps1 config_samples\sphere_distant.ini config_samples\multiple_sphere.ini
```

Blender を標準外の場所にインストールしている場合は、実行ファイルを指定できます。

```powershell
.\run_blender.ps1 config_samples\bunny_monochrome.ini -BlenderExe "D:\Apps\Blender 5.2\blender.exe"
```

`blender` コマンドをどのフォルダーからも直接使いたい場合は、Blender のインストールフォルダー（`blender.exe` がある場所）を Windows のユーザー環境変数 `Path` に追加し、新しいターミナルを開いてください。インストール先が不明な場合は、Windows のスタートメニューで Blender を検索し、「ファイルの場所を開く」から実体の場所を確認できます。

Blender を起動せず、システムの Python で設定・参照ファイルを確認できます。

```powershell
python render_object.py --validate-only config_samples\bunny_monochrome.ini
python -m unittest discover -s tests -v
```

`--validate-only` は Blender 5.2 のAPI実行を検証するものではありません。レンダリングには Blender の同梱 Python から実行してください。

## 補助ツール

```powershell
python misc\directional2euler.py directions.csv euler.csv
python misc\viewnpy.py output_dir\Sphere\normals.npy
python working_dir\visualization.py working_dir\light.csv light.png
```

`directional2euler.py` は方向ベクトル CSV / テキストを XYZ Euler 角 [rad] に変換します。`viewnpy.py` は NPY 配列を表示し、`--save` を指定すると画像に保存します。

## 出力

設定ファイルの `out_dir` の下にオブジェクト名のフォルダーが作成されます。複数ビューの場合は `view_001` などの下に画像が保存されます。

- `001.png` など: 光源設定ごとのレンダー画像
- `depth.png`, `normals.png`, `normals_alt.png`: 深度・法線画像
- `distance.npy`, `depth.npy`, `mask.npy`, `mask_alt.npy`, `normals.npy`, `normals_alt.npy`: 配列形式の形状データ
- `filenames.ini`: 画像と光源・カメラ・オブジェクト情報の対応表
- `save.ini`, `time.txt`: 使用設定と経過時間

配列は画像と同じ高さ・幅で保存され、行の先頭は画像の上端です。`distance.npy` は実距離、`depth.npy` は有効領域を 0–1 に正規化した深度、`mask*.npy` は 0/1 のマスクです。

## Blender 2.8 設定からの移行

- OBJ、PLY、STL は Blender 5.2 の `bpy.ops.wm.*_import` APIを使用します。FBX / X3D は対応する I/O 拡張機能が有効な環境で利用できます。
- Principled BSDF の旧ソケット名は Blender 5.2 の名前に対応付けます。旧 `subsurface_color` は専用入力がない場合に `base_color` へ反映します。
- 深度・法線データは Compositor から一時 OpenEXR に出力して取得します。`Render Result.layers` に依存せず、最終的な `.npy` / `.png` の形式は従来どおりです。
- 既定デバイスは CPU です。GPUを指定して利用可能なデバイスがない場合は、理由を表示して停止します。
- `tile_x` / `tile_y` はBlender 5.2では効果がないため無視されます。古いINIから削除して構いません。
- `denoising_legacy` は互換設定として扱い、`denoising` と同じCyclesデノイズを有効にします。
- 相対パスは原則として設定ファイルの場所を基準に解決します。旧形式の生成設定（`misc\cfg`）を使う場合は、プロジェクトルートから実行してください。`working_dir` が設定ファイル基準で見つからないときに、上位ディレクトリや起動時のカレントディレクトリも検索する互換動作があります。

INI の全項目とライト・ビュー CSV の形式は [config_tutorial.txt](./config_tutorial.txt) を参照してください。コンテナーで使う場合は、Blender 5.2 の公式バイナリを使う [Dockerfile](./Dockerfile) を利用できます。
