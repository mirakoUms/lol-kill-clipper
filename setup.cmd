@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-portable.txt
if errorlevel 1 goto failed
if not exist "config.yaml" copy "config.example.yaml" "config.yaml" >nul
if not exist "workflow.yaml" copy "workflow.example.yaml" "workflow.yaml" >nul
echo Setup complete. Set client_dir in workflow.yaml, then use start_clips.cmd.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11+ with PATH enabled and check Internet access.
pause
exit /b 1
