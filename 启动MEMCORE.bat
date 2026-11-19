@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

rem 优先用 py 启动器，其次 PATH 上的 python
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
    echo [MEMCORE] 未找到 Python，请先安装 Python 3.10+ 并勾选 "Add to PATH"。
    pause
    exit /b 1
)

rem 依赖缺失时自动安装
%PY% -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo [MEMCORE] 首次运行，正在安装依赖...
    %PY% -m pip install -r requirements.txt
)

%PY% desktop.py
if errorlevel 1 pause
