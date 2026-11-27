@echo off
cd /d "%~dp0"
set "PYEXE=python"
if exist "%~dp0runtime\python\python.exe" set "PYEXE=%~dp0runtime\python\python.exe"
"%PYEXE%" -B "%~dp0server.py"
if "%errorlevel%"=="75" exit /b 0
echo.
echo Server stopped. Press any key to close this window.
pause >nul
