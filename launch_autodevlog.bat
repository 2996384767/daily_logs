@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PROJECT_DIR=%~dp0"
if not defined PYTHON_EXE set "PYTHON_EXE=D:\anaconda3\envs\deeplearning\python.exe"
if not defined AUTODEVLOG_EDITOR set "AUTODEVLOG_EDITOR=code --wait"
if not defined AUTODEVLOG_MODE set "AUTODEVLOG_MODE=quick"

if not exist "%PYTHON_EXE%" (
    echo [Auto-DevLog] Python environment not found:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
"%PYTHON_EXE%" "%PROJECT_DIR%main.py" new --mode "%AUTODEVLOG_MODE%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [Auto-DevLog] Log flow did not finish cleanly. See message above.
    pause
    exit /b %EXIT_CODE%
)

for /f "usebackq delims=" %%I in (`"%PYTHON_EXE%" "%PROJECT_DIR%main.py" view-path`) do set "VIEW_PATH=%%I"
if not defined VIEW_PATH set "VIEW_PATH=%PROJECT_DIR%README.md"
start "" "%VIEW_PATH%"
exit /b 0
