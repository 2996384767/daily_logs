@echo off
setlocal

set "PROJECT_DIR=%~dp0"
if not defined PYTHON_EXE set "PYTHON_EXE=D:\anaconda3\envs\deeplearning\python.exe"
if not defined AUTODEVLOG_EDITOR set "AUTODEVLOG_EDITOR=code --wait"

if not exist "%PYTHON_EXE%" (
    echo [Auto-DevLog] Python environment not found:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

echo [Auto-DevLog] Opening editor for a new dev log...
"%PYTHON_EXE%" "%PROJECT_DIR%main.py" new
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [Auto-DevLog] Log flow did not finish cleanly. See message above.
    pause
    exit /b %EXIT_CODE%
)

echo.
echo [Auto-DevLog] Opening README.md so you can review the latest timeline...
start "" "%PROJECT_DIR%README.md"
exit /b 0
