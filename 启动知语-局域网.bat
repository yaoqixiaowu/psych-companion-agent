@echo off
title 知语 · 心理陪伴智能体（局域网版）
cd /d "%~dp0"

echo ============================================================
echo   知语 · 心理陪伴智能体  ·  局域网版
echo ============================================================
echo.
echo  【怎么用】
echo    1. 启动完成后，窗口里会出现一行 http://10.x.x.x:5000
echo    2. 把那行地址发给同一个 WiFi / 局域网里的同学
echo    3. 他们直接用浏览器打开就能对话，什么都不用装
echo.
echo  【注意】这个黑色窗口不能关闭，关掉别人就打不开了。
echo          停止服务：在本窗口按 Ctrl + C
echo.
echo  【安全】当前版本没有登录验证，同一网络内任何人都能打开，
echo          请只在校园网 / 家里的网络中使用。
echo.

REM ================= 第一步：找一个能用的 Python 环境 =================
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
    echo.
    echo         请先双击运行本目录下的「修复运行环境.bat」，
    echo         它会自动把环境修好，然后再双击本文件即可。
    echo.
    pause
    exit /b 1
)

REM ================= 第二步：处理端口被占用 =================
set "PORT=5000"
set "OLDPID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do set "OLDPID=%%p"

if defined OLDPID (
    tasklist /FI "PID eq %OLDPID%" /FO CSV /NH 2>nul | findstr /i "python.exe" >nul
    if not errorlevel 1 (
        echo  [提示] 上一版的知语还在运行，先自动关掉它...
        taskkill /F /PID %OLDPID% >nul 2>nul
        ping -n 2 127.0.0.1 >nul
    ) else (
        echo  [警告] 端口 %PORT% 被别的程序占用了（PID %OLDPID%）。
        echo         请关掉那个程序再试，或者把本文件里的 PORT 改成 5001。
        echo.
        pause
        exit /b 1
    )
)

REM ================= 第三步：启动服务 =================
set "PSYCH_HOST=0.0.0.0"
set "PSYCH_PORT=%PORT%"

echo  正在启动，请稍候（第一次要等 3~5 秒）...
echo.

set PYTHONIOENCODING=gbk
%PYTHON% web.py

echo.
echo  服务已停止，同学将无法再访问。
echo.
pause
