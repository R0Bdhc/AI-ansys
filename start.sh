#!/usr/bin/env bash
# cae-agent 启动脚本（Linux/macOS）。PORT 未设置时默认 8000。
set -e
cd "$(dirname "$0")"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
command -v "$PY" >/dev/null 2>&1 || { echo "[错误] 未找到 python3，请安装 Python 3.11+。"; exit 1; }

"$PY" scripts/check_env.py

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "[启动] http://127.0.0.1:${PORT}/dashboard  （Ctrl+C 停止）"
exec "$PY" -m uvicorn main:app --host "$HOST" --port "$PORT"
