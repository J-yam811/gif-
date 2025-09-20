# GIF化ツール（シンプル高品質・動画→GIF）

Pythonスクリプトで動画（または画像列）から高品質なGIFを生成します。内部でFFmpegを使用し、必要に応じてgifsicleで最終最適化を行います。

- 高品質パイプライン：`fps` + `scale` + `palettegen/paletteuse`（Sierra2_4A等のディザ）
- 既定は軽量＆見栄え重視（fps=12、最大幅480px、256色、無限ループ）
- 区間切り出し（`--start`/`--duration`/`--to`）に対応
- 画像列（`--pattern` で `*.png` や `frame%04d.png`）にも対応
- `gifsicle` があれば `-O3`/`--lossy` による追加圧縮

## 必要環境

- macOS / Linux / WSL など（Windowsも可だがパス引用に注意）
- Python 3.8+
- FFmpeg（必須）
  - macOS: `brew install ffmpeg`
- gifsicle（任意、最終圧縮に使用）
  - macOS: `brew install gifsicle`

## 使い方

```
cd /Users/yamasejun/開発/GIF化ツール
python3 gifify.py input.mp4 -o out.gif
```

主なオプション：

- `-o, --output` 出力GIFパス（省略時は `input名.gif`）
- `--fps` フレームレート（既定: 12）
- `--max-width` 最大幅（既定: 480、原画が小さければ縮小しません）
- `--colors` パレット色数（既定: 256）
- `--dither` ディザ（`sierra2_4a|bayer|floyd_steinberg|none`、既定: sierra2_4a）
- `--loop` ループ回数（既定: 0=無限）
- `--start` 切り出し開始（例: `5`, `00:00:05.3`）
- `--duration` 切り出し長さ（秒 or 時間表記）
- `--to` 終了時刻（開始と併用可）
- `--optimize` 生成後に `gifsicle -O3` を適用（`--lossy N` 併用可）
- `--pattern` 動画ではなく画像列から作る（`"frames/*.png"` など）
- `--verbose` 実行コマンド表示

### 例

- 高品質・小さめのGIF（デフォルト設定）
  ```
  python3 gifify.py demo.mp4 -o demo.gif
  ```
- フレームレート15、最大幅640pxで作成
  ```
  python3 gifify.py demo.mp4 -o demo_640.gif --fps 15 --max-width 640
  ```
- 5秒目から8秒間を抽出
  ```
  python3 gifify.py demo.mp4 -o cut.gif --start 5 --duration 8
  ```
- 画像列（PNG）から作成（glob）
  ```
  python3 gifify.py --pattern "frames/*.png" -o anim.gif --fps 10
  ```
- 生成後に最適化（損失圧縮レベル80）
  ```
  python3 gifify.py demo.mp4 -o demo_optimized.gif --optimize --lossy 80
  ```

### ドラッグ&ドロップ（ローカルWeb UI）

ブラウザ上でファイルをドラッグ&ドロップしてGIF化できます。

```
python3 webui.py --open
```

- 起動後に `http://127.0.0.1:8765/` が開きます。
- 画面のドロップゾーンに動画をドラッグするだけで変換が始まります。
- FPS/最大幅/開始・長さ/ディザ/最適化等を画面から指定可能。

### Finderアプリ（ダブルクリック/ドラッグ対応）

- `GIF化ツール.app` をダブルクリックすると Web UI サーバーをバックグラウンドで起動し、ブラウザを開きます。
- 動画ファイルを `GIF化ツール.app` のアイコンにドラッグ&ドロップすると、その場で `gifify.py` が走り、ファイルと同じ場所に GIF が生成されます。
- Dock に常駐させれば Finder からいつでもアクセスでき、1クリックまたはドラッグ操作だけで利用可能です。
- 通知が表示されない場合は、システム設定 → 通知と集中モード で「Script Editor」/「osascript」等の通知を許可してください。

## 実装メモ

- FFmpeg単発フィルタグラフ（`split`→`palettegen`→`paletteuse`）で2パス相当を1コマンド化
- `scale='min(iw,MAXW)':-1:flags=lanczos` で入力幅を超えない最大幅縮小
- `-ss/-t/-to` は入力に対して適用（パレット生成・適用の対象一致）
- ループは `-loop 0`（無限）などをGIF muxerに指定
- gifsicle が見つかれば `-O3` と任意の `--lossy N` で再圧縮

## よくある質問

- 文字化けする/日本語パスで失敗する
  - Python経由で安全に実行しますが、シェル直叩きより安全です。問題が続く場合は `--verbose` でコマンドを確認してください。
- 画質が荒い/容量が大きい
  - `--fps` を下げる/`--max-width` を小さくする/`--colors` を減らす/`--dither bayer` にする/`--optimize --lossy N` を試してください。

---

作成: `/Users/yamasejun/開発/GIF化ツール`
