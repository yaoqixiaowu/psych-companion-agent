@echo off
title 知语 · 修复运行环境
cd /d "%~dp0"

echo ============================================================
echo   知语 · 修复运行环境
echo ============================================================
echo.
echo  什么时候用：换了电脑、把项目复制到 U 盘后，
echo              双击启动脚本报错"没有找到运行环境"时。
echo.
echo  它会做什么：在项目里重新生成一个自带的 Python 环境，
echo              不需要联网（优先复用项目里已有的依赖包）。
echo.

REM ---------- 现有环境还能用就不用修 ----------
if exist ".venv-local\Scripts\python.exe" (
    ".venv-local\Scripts\python.exe" -c "import flask, openai, dotenv" >nul 2>nul
    if not errorlevel 1 (
        echo  [OK] 运行环境是好的，不需要修复。
        echo       直接双击「启动知语-局域网.bat」即可。
        echo.
        pause
        exit /b 0
    )
)

REM ---------- 找一个基础 Python ----------
echo  正在查找本机 Python...
set "BASE_PY="

python -c "import sys" >nul 2>nul
if not errorlevel 1 set "BASE_PY=python"

if not defined BASE_PY (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "BASE_PY=py -3"
)

if not defined BASE_PY (
    for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%d\python.exe" set "BASE_PY=%%d\python.exe"
    )
)

if not defined BASE_PY (
    for /d %%d in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
        if exist "%%d\python.exe" set "BASE_PY=%%d\python.exe"
    )
)

if not defined BASE_PY (
    echo  [错误] 这台电脑上没有找到 Python。
    echo         请先安装 Python 3.10 或更高版本，
    echo         安装时务必勾选 "Add Python to PATH"：
    echo            https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo  将使用：%BASE_PY%
echo.
echo  正在创建运行环境...

if exist ".venv-local" rmdir /s /q ".venv-local"
%BASE_PY% -m venv ".venv-local"

if not exist ".venv-local\Scripts\python.exe" (
    echo  [错误] 环境创建失败，请把上面的报错截图发给组长。
    echo.
    pause
    exit /b 1
)

REM ---------- 优先复用项目里旧环境已下好的依赖，免联网 ----------
if exist ".venv\Lib\site-packages" (
    echo  正在复用项目里已有的依赖包...
    xcopy ".venv\Lib\site-packages" ".venv-local\Lib\site-packages" /E /I /Y /Q >nul 2>nul
)

".venv-local\Scripts\python.exe" -c "import flask, openai, dotenv, edge_tts" >nul 2>nul
if errorlevel 1 (
    echo  依赖不完整，正在联网安装（可能需要几分钟，请耐心等待）...
    ".venv-local\Scripts\pip.exe" install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  [错误] 安装失败，请检查网络连接后重新运行本文件。
        echo.
        pause
        exit /b 1
    )
)

echo.
echo  [完成] 运行环境已修好。
echo         现在双击「启动知语-局域网.bat」就能用了。
echo.
pause
