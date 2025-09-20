#!/bin/zsh
set -euo pipefail
cd -- "$(dirname "$0")"

if [ "$#" -gt 0 ]; then
  for f in "$@"; do
    if [ ! -f "$f" ]; then
      echo "[WARN] ファイルが見つかりません: $f" >&2
      continue
    fi
    out="${f%.*}.gif"
    echo "[INFO] 変換: $f -> $out"
    /usr/bin/env python3 gifify.py "$f" -o "$out" || exit 1
  done
  echo "[DONE] 変換が完了しました。"
else
  /usr/bin/env python3 webui.py --open
fi
