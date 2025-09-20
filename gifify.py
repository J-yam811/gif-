#!/usr/bin/env python3
"""
gifify.py — シンプル高品質な動画/画像列→GIF変換CLI

依存: FFmpeg（必須）、gifsicle（任意）。

主な特長:
- palettegen/paletteuse と Lanczos スケールで高品質化
- 既定設定は軽量＆見栄え重視（fps=12, max-width=480, colors=256, loop=0）
- 区間切り出し（--start/--duration/--to）
- 画像列（--pattern）対応（glob または printf 書式）
- 任意で gifsicle による最適化（-O3/--lossy）

使用例:
  python3 gifify.py input.mp4 -o out.gif
  python3 gifify.py --pattern "frames/*.png" -o out.gif --fps 10
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def which(bin_name: str) -> str | None:
    return shutil.which(bin_name)


def require_binary(bin_name: str) -> str:
    path = which(bin_name)
    if path is None:
        print(f"[ERROR] 必須コマンドが見つかりません: {bin_name}", file=sys.stderr)
        if bin_name == "ffmpeg":
            print("  macOS: brew install ffmpeg", file=sys.stderr)
        sys.exit(2)
    return path


def build_filter(fps: float, max_width: int | None, colors: int, dither: str) -> str:
    parts = []
    # フレームレート整形
    parts.append(f"fps={fps}")

    # スケール：最大幅指定がある場合だけ縮小（原寸以下のときはそのまま）
    if max_width is not None:
        # min(iw,MAXW) で元幅を超えないようにする
        parts.append(f"scale='min(iw,{int(max_width)})':-1:flags=lanczos")

    # split→palettegen→paletteuse
    # ditherは ffmpeg の paletteuse に合わせて指定
    # 例: sierra2_4a, bayer, floyd_steinberg, none
    core = ",".join(parts)
    # palettegen の max_colors と stats_mode=diff でブレ抑制
    palettegen = f"[s0]palettegen=stats_mode=diff:max_colors={int(colors)}[p]"
    # paletteuse の dither
    if dither == "none":
        dither_opt = "dither=none"
    elif dither == "bayer":
        # bayer_scale は軽量寄りの既定値
        dither_opt = "dither=bayer:bayer_scale=5"
    elif dither == "floyd_steinberg":
        dither_opt = "dither=floyd_steinberg"
    else:
        # 既定: sierra2_4a（高品質）
        dither_opt = "dither=sierra2_4a"

    paletteuse = f"[s1][p]paletteuse={dither_opt}"

    if core:
        vf = f"{core},split[s0][s1];{palettegen};{paletteuse}"
    else:
        vf = f"split[s0][s1];{palettegen};{paletteuse}"
    return vf


def detect_input_mode(input_path: Path | None, pattern: str | None) -> str:
    if pattern:
        return "images"
    if input_path is None:
        print("[ERROR] 入力を指定してください（動画ファイル or --pattern）", file=sys.stderr)
        sys.exit(2)
    video_exts = {
        ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpg", ".mpeg",
    }
    if input_path.suffix.lower() in video_exts:
        return "video"
    # その他も動画として扱う（ffmpegに任せる）
    return "video"


def add_time_opts(cmd: list[str], start: str | None, duration: str | None, to: str | None) -> None:
    # -ss/-t/-to は入力直前に入れて入力トリム（paletteと一致させる）
    if start:
        cmd.extend(["-ss", str(start)])
    if duration:
        cmd.extend(["-t", str(duration)])
    if to:
        cmd.extend(["-to", str(to)])


def run(cmd: list[str], verbose: bool = False) -> int:
    if verbose:
        print("[cmd]", " ".join(shlex.quote(c) for c in cmd), file=sys.stderr)
    proc = subprocess.run(cmd)
    return proc.returncode


def make_gif(
    input_path: Path | None,
    output_path: Path,
    fps: float,
    max_width: int | None,
    colors: int,
    dither: str,
    loop: int,
    start: str | None,
    duration: str | None,
    to: str | None,
    pattern: str | None,
    optimize: bool,
    lossy: int | None,
    overwrite: bool,
    verbose: bool,
) -> None:
    ffmpeg = require_binary("ffmpeg")
    gifsicle = which("gifsicle") if optimize else None

    vf = build_filter(fps=fps, max_width=max_width, colors=colors, dither=dither)

    tmp_out = output_path
    if optimize and gifsicle:
        # gifsicleで上書きするため、一時的に別名を経由
        tmp_out = output_path.with_suffix(".tmp.gif")

    # 既存ファイル処理
    if tmp_out.exists() and not overwrite:
        print(f"[ERROR] 出力が既に存在します: {tmp_out}", file=sys.stderr)
        sys.exit(1)

    # FFmpegコマンド構築
    cmd: list[str] = [ffmpeg, "-hide_banner"]
    if overwrite:
        cmd.append("-y")
    else:
        cmd.append("-n")

    # 入力
    mode = detect_input_mode(input_path, pattern)
    if mode == "images":
        # 画像列入力
        add_time_opts(cmd, start, duration, to)  # 静止画列でもオプションは許容（通常無視）
        pat = pattern or ""
        if "*" in pat or "?" in pat or "[" in pat:
            # glob パターン
            cmd.extend(["-pattern_type", "glob", "-i", pat])
        else:
            # printf 形式（%03d 等）
            cmd.extend(["-i", pat])
    else:
        # 動画入力
        add_time_opts(cmd, start, duration, to)
        cmd.extend(["-i", str(input_path)])

    # フィルタ + ループ指定
    cmd.extend(["-vf", vf, "-loop", str(loop), str(tmp_out)])

    code = run(cmd, verbose=verbose)
    if code != 0:
        print("[ERROR] FFmpeg 実行に失敗しました", file=sys.stderr)
        sys.exit(code)

    # gifsicle最適化
    if optimize:
        if gifsicle is None:
            print("[WARN] gifsicle が見つからないため --optimize をスキップしました。", file=sys.stderr)
        else:
            gcmd = [gifsicle, "-O3", str(tmp_out), "-o", str(output_path)]
            if lossy is not None:
                gcmd.insert(1, f"--lossy={int(lossy)}")
            code = run(gcmd, verbose=verbose)
            if code != 0:
                print("[ERROR] gifsicle 実行に失敗しました", file=sys.stderr)
                sys.exit(code)
            # 一時ファイルを置換に使った場合は削除試行
            if tmp_out != output_path:
                try:
                    tmp_out.unlink(missing_ok=True)
                except Exception:
                    pass

    print(f"[OK] GIF生成完了: {output_path}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="動画/画像列から高品質GIFを生成するシンプルCLI")
    p.add_argument("input", nargs="?", help="入力動画ファイルパス（--pattern 指定時は省略可）")
    p.add_argument("-o", "--output", help="出力GIFパス（省略時は input名.gif）")
    p.add_argument("--fps", type=float, default=12.0, help="出力GIFフレームレート（既定: 12）")
    p.add_argument("--max-width", type=int, default=480, help="最大幅（既定: 480。原寸が小さければ維持）")
    p.add_argument("--colors", type=int, default=256, help="パレット色数（既定: 256）")
    p.add_argument(
        "--dither",
        choices=["sierra2_4a", "bayer", "floyd_steinberg", "none"],
        default="sierra2_4a",
        help="ディザ手法（既定: sierra2_4a）",
    )
    p.add_argument("--loop", type=int, default=0, help="ループ回数。0=無限（既定）")
    p.add_argument("--start", help="開始時刻（秒または 00:00:00.000）")
    p.add_argument("--duration", help="継続時間（秒または 00:00:00.000）")
    p.add_argument("--to", help="終了時刻（開始と併用可）")
    p.add_argument("--pattern", help="画像列パターン（例: 'frames/*.png' or 'frame%04d.png'）")
    p.add_argument("--optimize", action="store_true", help="gifsicle による最終最適化を実施")
    p.add_argument("--lossy", type=int, help="gifsicle の損失圧縮レベル（0-200程度）")
    p.add_argument("--no-overwrite", action="store_true", help="出力が存在する場合は上書きしない")
    p.add_argument("--verbose", action="store_true", help="実行コマンドを表示")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    input_path = Path(args.input) if args.input else None
    if input_path is not None and not input_path.exists() and args.pattern is None:
        print(f"[ERROR] 入力が存在しません: {input_path}", file=sys.stderr)
        return 2

    # 出力パス決定
    if args.output:
        out = Path(args.output)
    else:
        if input_path is None:
            print("[ERROR] --output を明示指定してください（--pattern 使用時）", file=sys.stderr)
            return 2
        out = input_path.with_suffix(".gif")

    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        make_gif(
            input_path=input_path,
            output_path=out,
            fps=args.fps,
            max_width=None if args.max_width <= 0 else args.max_width,
            colors=max(2, min(256, int(args.colors))),
            dither=args.dither,
            loop=args.loop,
            start=args.start,
            duration=args.duration,
            to=args.to,
            pattern=args.pattern,
            optimize=bool(args.optimize),
            lossy=args.lossy,
            overwrite=not args.no_overwrite,
            verbose=bool(args.verbose),
        )
        return 0
    except KeyboardInterrupt:
        print("[INTERRUPTED] ユーザーにより中断されました", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

