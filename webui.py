#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webui.py — ブラウザでドラッグ&ドロップしてGIF化するローカルWeb UI。

依存: Python3 標準ライブラリ + FFmpeg（必須）+ gifsicle（任意）。
使い方:
  python3 webui.py --open
  → http://127.0.0.1:8765 を開き、動画をドロップ
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import traceback
import cgi
import urllib.parse
import webbrowser

from gifify import make_gif


HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"


def _parse_bool(v: str | None) -> bool:
    if v is None:
        return False
    v = v.lower()
    return v in ("1", "true", "on", "yes")


class DnDHandler(BaseHTTPRequestHandler):
    server_version = "GififyWebUI/1.0"

    def _add_cors(self) -> None:
        # ローカル以外や file:// からの利用にも備える（開発用途）
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._add_cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._send_file(STATIC / "index.html", content_type="text/html; charset=utf-8")
            return
        if path == "/healthz":
            self._send_plain(HTTPStatus.OK, "ok")
            return
        # 静的ファイル（簡易）
        candidate = (STATIC / path.lstrip("/")).resolve()
        if candidate.is_file() and candidate.parent == STATIC:
            mime = "text/plain; charset=utf-8"
            if str(candidate).endswith(".css"):
                mime = "text/css; charset=utf-8"
            elif str(candidate).endswith(".js"):
                mime = "text/javascript; charset=utf-8"
            self._send_file(candidate, content_type=mime)
            return
        self._send_plain(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/convert":
            self._handle_convert()
            return
        self._send_plain(HTTPStatus.NOT_FOUND, "Not Found")

    def _handle_convert(self) -> None:
        # 100-continue に対応（大きいアップロードで必要な場合）
        if self.headers.get("Expect", "").lower() == "100-continue":
            self.send_response_only(HTTPStatus.CONTINUE)
            self.end_headers()

        # リクエスト情報
        ctype, _pdict = cgi.parse_header(self.headers.get("Content-Type", ""))
        length = int(self.headers.get("Content-Length", "0") or 0)
        print(f"[POST] /convert ctype={ctype} length={length}")

        # パラメータはクエリからも受け取れるようにする（raw upload 対応）
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)

        def qget(name: str, default: str | None = None) -> str | None:
            return (q.get(name, [default])[0])

        # デフォルト値
        fps = float(qget("fps", "12") or 12)
        max_width = int(qget("max_width", "480") or 480)
        colors = int(qget("colors", "256") or 256)
        dither = qget("dither", "sierra2_4a") or "sierra2_4a"
        loop = int(qget("loop", "0") or 0)
        start = qget("start")
        duration = qget("duration")
        to = qget("to")
        optimize = _parse_bool(qget("optimize"))
        lossy = qget("lossy")
        lossy_i = int(lossy) if lossy not in (None, "") else None

        # 入力ファイルの取得
        filename = qget("filename", "upload.bin")
        if ctype == "application/octet-stream":
            # 生データを受け取り、そのまま一時ファイルへ
            if length <= 0:
                self._send_plain(HTTPStatus.BAD_REQUEST, "missing or invalid Content-Length")
                return
            suffix = Path(filename).suffix or ".bin"
            with tempfile.NamedTemporaryFile(prefix="gifify_in_", suffix=suffix, delete=False) as tf:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    tf.write(chunk)
                    remaining -= len(chunk)
                in_path = Path(tf.name)
        elif ctype == "multipart/form-data":
            # 互換: フォームで送られてきた場合
            try:
                fs = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                        "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                    },
                    keep_blank_values=True,
                )
            except Exception as e:  # noqa: BLE001
                self._send_plain(HTTPStatus.BAD_REQUEST, f"form parse error: {e}")
                return

            fitem = fs["file"] if "file" in fs else None
            if not fitem or not getattr(fitem, "filename", None):
                self._send_plain(HTTPStatus.BAD_REQUEST, "no file")
                return

            # オプション上書き（フォーム優先）
            def get(name: str, default: str | None = None) -> str | None:
                if name in fs and fs[name].value != "":
                    return fs[name].value
                return default
            fps = float(get("fps", str(fps)) or fps)
            max_width = int(get("max_width", str(max_width)) or max_width)
            colors = int(get("colors", str(colors)) or colors)
            dither = get("dither", dither) or dither
            loop = int(get("loop", str(loop)) or loop)
            start = get("start", start) or start
            duration = get("duration", duration) or duration
            to = get("to", to) or to
            optimize = _parse_bool(get("optimize", "true" if optimize else None))
            lossy = get("lossy", lossy)
            lossy_i = int(lossy) if lossy not in (None, "") else lossy_i

            filename = getattr(fitem, "filename", filename)
            suffix = Path(filename).suffix or ".bin"
            with tempfile.NamedTemporaryFile(prefix="gifify_in_", suffix=suffix, delete=False) as tf:
                try:
                    fitem.file.seek(0)
                except Exception:
                    pass
                shutil.copyfileobj(fitem.file, tf, length=1024 * 1024)
                in_path = Path(tf.name)
        else:
            self._send_plain(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, f"unsupported content-type: {ctype}")
            return

        # 出力パス
        with tempfile.NamedTemporaryFile(prefix="gifify_out_", suffix=".gif", delete=False) as of:
            out_path = Path(of.name)

        try:
            make_gif(
                input_path=in_path,
                output_path=out_path,
                fps=fps,
                max_width=None if max_width <= 0 else max_width,
                colors=max(2, min(256, colors)),
                dither=dither,
                loop=loop,
                start=start,
                duration=duration,
                to=to,
                pattern=None,
                optimize=optimize,
                lossy=lossy_i,
                overwrite=True,
                verbose=False,
            )

            # 結果返却
            gif_bytes = out_path.read_bytes()
            outname = Path(filename).with_suffix(".gif").name
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/gif")
            self._add_cors()
            self.send_header("Content-Length", str(len(gif_bytes)))
            self.send_header("Content-Disposition", f"attachment; filename=\"{outname}\"")
            self.end_headers()
            self.wfile.write(gif_bytes)
        except BaseException as e:
            print(f"[ERROR] convert failed: {e}", file=sys.stderr)
            traceback.print_exc()
            self._send_plain(HTTPStatus.INTERNAL_SERVER_ERROR, f"convert error: {e}")
        finally:
            try:
                in_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _send_plain(self, status: HTTPStatus, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self._add_cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, *, content_type: str) -> None:
        if not path.exists():
            self._send_plain(HTTPStatus.NOT_FOUND, "Not Found")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self._add_cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="ドラッグ&ドロップでGIF化するローカルWeb UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="起動後にブラウザを開く")
    args = ap.parse_args(argv)

    httpd = ThreadingHTTPServer((args.host, args.port), DnDHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"[INFO] Web UI: {url}")

    if args.open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
