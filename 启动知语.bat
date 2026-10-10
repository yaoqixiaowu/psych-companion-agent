@echo off
chcp 65001 > nul
title 知语 · 心理陪伴智能体

echo ============================================================
echo   知语 · 心理陪伴智能体
echo ============================================================
echo.

REM 优先使用项目内的虚拟环境，避免要求使用者配置 Python 环境
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    echo [提示] 未找到虚拟环境，尝试使用系统 Python
    echo        如未安装依赖，请运行：pip install -r requirements.txt
    echo.
    set PYTHON=python
)

REM 默认仅本机可访问。若需让同一局域网的同学访问，
REM 改用 启动知语-局域网.bat
if "%PSYCH_HOST%"=="" (
    echo 模式：本机访问（仅此电脑可用）
    echo.
    echo 正在启动服务...
    start "" http://127.0.0.1:5000
    %PYTHON% web.py
) else (
    echo 模式：局域网访问（同一 WiFi 下的设备可用）
    echo.
    echo 正在启动服务，启动后屏幕上会显示可访问的地址...
    %PYTHON% web.py
    echo.
    echo 服务已停止。
)

echo.
pause
