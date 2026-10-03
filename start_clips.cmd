@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See QUICKSTART.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 make_clips.py %*
set "clipper_exit=%errorlevel%"
if not "%clipper_exit%"=="0" echo Export failed. Read the message above.
pause
exit /b %clipper_exit%
