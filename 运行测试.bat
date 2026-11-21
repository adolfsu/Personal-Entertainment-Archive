@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
if exist "runtime\python\python.exe" set "PY=runtime\python\python.exe"
echo ==========================================
echo   娱乐档案 · 核心测试（不会碰真实档案）
echo ==========================================
"%PY%" -m unittest discover -s tests -v
echo.
pause
