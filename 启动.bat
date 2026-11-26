@echo off
cd /d "%~dp0"
rem 版本号唯一来源：根目录 VERSION 文件；读不到就只显示 Archive Server
set "VER="
if exist "%~dp0VERSION" for /f "usebackq delims=" %%v in ("%~dp0VERSION") do if not defined VER set "VER=%%v"
if defined VER if /i "%VER:~0,1%"=="v" set "VER=%VER:~1%"
if defined VER (title Archive Server v%VER%) else (title Archive Server)
set "PYEXE="
if exist "%~dp0runtime\python\python.exe" set "PYEXE=%~dp0runtime\python\python.exe"
if defined PYEXE goto run
python -c "import sys" >nul 2>nul
if errorlevel 1 goto missing
set "PYEXE=python"
:run
"%PYEXE%" server.py
if "%errorlevel%"=="75" exit /b 0
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
