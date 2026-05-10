@echo off
setlocal
set "AUTODEVLOG_MODE=editor"
call "%~dp0launch_autodevlog.bat"
exit /b %ERRORLEVEL%
