@echo off
chcp 65001 > nul
title 知语 · 心理陪伴智能体

echo ============================================================
echo   知语 · 心理陪伴智能体
echo ============================================================
echo.
echo  本窗口是服务主进程，请保持它开着。
echo  关闭本窗口 = 停止服务，其他人将无法访问。
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境
    echo.
    echo 请先在命令行执行：
    echo     python -m venv .venv
    echo     .venv\Scripts\activate
    echo     pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo 正在启动服务，启动后会显示可访问的地址...
echo.

set PSYCH_HOST=0.0.0.0
.venv\Scripts\python.exe web.py

echo.
echo 服务已停止，其他人将无法访问。
pause
