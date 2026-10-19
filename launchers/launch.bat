@echo off
rem Qwen Server Desktop 启动器（Windows）
rem 双击即可运行；会自动探测可用的 Python 解释器。

setlocal enabledelayedexpansion

set "HERE=%~dp0"
pushd "%HERE%.."
set "APP_DIR=%CD%"
popd
set "ENTRY=%APP_DIR%\qwen_desktop.py"

if not exist "%ENTRY%" (
    echo 找不到入口文件：%ENTRY%
    pause
    exit /b 1
)

set "PY="

rem 1) 用户显式指定
if defined QWEN_DESKTOP_PYTHON (
    if exist "%QWEN_DESKTOP_PYTHON%" set "PY=%QWEN_DESKTOP_PYTHON%"
)

rem 2) py 启动器（python.org 官方安装包会装这个）
if not defined PY (
    where py >nul 2>&1 && (
        for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
    )
)

rem 3) PATH 里的 python
if not defined PY (
    for /f "delims=" %%i in ('where pythonw 2^>nul') do (
        if not defined PY set "PY=%%i"
    )
)
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PY set "PY=%%i"
    )
)

rem 4) 常见安装位置
if not defined PY (
    for %%D in (
        "%LOCALAPPDATA%\Programs\Python\Python313"
        "%LOCALAPPDATA%\Programs\Python\Python312"
        "%LOCALAPPDATA%\Programs\Python\Python311"
        "%LOCALAPPDATA%\Programs\Python\Python310"
        "%LOCALAPPDATA%\Programs\Python\Python39"
        "C:\Python313" "C:\Python312" "C:\Python311" "C:\Python310"
    ) do (
        if not defined PY if exist "%%~D\pythonw.exe" set "PY=%%~D\pythonw.exe"
    )
)

if not defined PY (
    echo.
    echo 找不到 Python 3。
    echo 请从 https://www.python.org/downloads/ 安装，
    echo 安装时记得勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

rem 用 pythonw 启动，避免留下黑色控制台窗口
start "" "%PY%" "%ENTRY%" %*
exit /b 0
