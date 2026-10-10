@echo off
chcp 65001 > nul
title 知语 · 心理陪伴智能体（局域网模式）

echo ============================================================
echo   知语 · 心理陪伴智能体 · 局域网模式
echo ============================================================
echo.
echo 此模式会让同一 WiFi / 局域网内的其他设备访问本服务。
echo.
echo [安全提示]
echo   当前版本没有登录验证，同网络内的任何人都能打开对话。
echo   请仅在可信的校园网或家庭网络中使用。
echo   启动后请不要关闭本窗口，否则他人将无法访问。
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先在命令行运行：
    echo        python -m venv .venv
    echo        .venv\Scripts\activate
    echo        pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo 正在启动服务...
echo.

set PSYCH_HOST=0.0.0.0
.venv\Scripts\python.exe web.py

echo.
echo 服务已停止，他人将无法再访问。
pause
