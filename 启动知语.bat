@echo off
title 知语 · 心理陪伴智能体（本机版）
cd /d "%~dp0"

echo ============================================================
echo   知语 · 心理陪伴智能体  ·  本机版
echo ============================================================
echo.
echo  本版本只有这台电脑能打开，别人访问不了。
echo  要让同学也能用，请改用「启动知语-局域网.bat」。
echo.

REM ================= 找一个能用的 Python 环境 =================
set "PYTHON="

if exist ".venv-local\Scripts\python.exe" (
    ".venv-local\Scripts\python.exe" -c "import flask" >nul 2>nul
    if not errorlevel 1 set "PYTHON=.venv-local\Scripts\python.exe"
)

if not defined PYTHON (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" -c "import flask" >nul 2>nul
        if not errorlevel 1 set "PYTHON=.venv\Scripts\python.exe"
    )
)

if not defined PYTHON (
    python -c "import flask" >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo  [错误] 没有找到可用的运行环境。
    echo         请先双击运行「修复运行环境.bat」。
    echo.
    pause
    exit /b 1
)

REM ================= 处理端口被占用 =================
set "PORT=5000"
set "OLDPID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do set "OLDPID=%%p"

if defined OLDPID (
    tasklist /FI "PID eq %OLDPID%" /FO CSV /NH 2>nul | findstr /i "python.exe" >nul
    if not errorlevel 1 (
        echo  [提示] 上一版的知语还在运行，先自动关掉它...
        taskkill /F /PID %OLDPID% >nul 2>nul
        ping -n 2 127.0.0.1 >nul
    )
)

REM ================= 启动服务 =================
set "PSYCH_PORT=%PORT%"

echo  正在启动，马上会自动打开浏览器...
echo.

start "" http://127.0.0.1:%PORT%
set PYTHONIOENCODING=gbk
%PYTHON% web.py

echo.
echo  服务已停止。
echo.
pause
