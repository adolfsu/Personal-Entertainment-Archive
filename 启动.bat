@echo off
title Archive Server
cd /d "%~dp0"
set "PYEXE="
if exist "%~dp0runtime\python\python.exe" set "PYEXE=%~dp0runtime\python\python.exe"
if defined PYEXE goto run
python -c "import sys" >nul 2>nul
if errorlevel 1 goto missing
set "PYEXE=python"
:run
"%PYEXE%" server.py
echo.
echo Server stopped. Press any key to close this window.
pause >nul
exit /b 0
:missing
echo.
echo Python not found on this PC.
echo Keep the "runtime" folder next to this file, or install Python 3 from python.org.
echo.
pause
exit /b 1
