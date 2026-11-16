@echo off
REM cae-agent 启动脚本（Windows）。PORT 未设置时默认 8000。
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请安装 Python 3.11+ 并加入 PATH。
    exit /b 1
)

python scripts\check_env.py
if errorlevel 1 (
    echo [错误] 环境自检未通过，请按上方输出修复后重试。
    exit /b 1
)

if "%PORT%"=="" set PORT=8000
if "%HOST%"=="" set HOST=0.0.0.0

echo [启动] http://127.0.0.1:%PORT%/dashboard  （Ctrl+C 停止）
python -m uvicorn main:app --host %HOST% --port %PORT%
