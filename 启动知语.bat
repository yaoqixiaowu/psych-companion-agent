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
    echo        如未安装依赖，请先运行：pip install -r requirements.txt
    echo.
    set PYTHON=python
)

echo 正在启动服务，浏览器将自动打开...
echo 关闭本窗口即可停止服务。
echo.

start "" http://127.0.0.1:5000
%PYTHON% web.py

echo.
echo 服务已停止。
pause
