@echo off
REM WorkFlowOS: one command to run everything (Windows).
cd /d "%~dp0backend"
echo Installing Python packages (first run takes a few minutes)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Python or pip is missing. Install Python 3.11 from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)
echo Making sure the automation browser is installed...
python -m playwright install chromium >nul 2>&1
if not exist "..\frontend\dist\index.html" goto build
goto run
:build
echo Building the web app - needs Node 18 or newer...
pushd ..\frontend
call npm install
call npm run build
popd
:run
echo.
echo   WorkFlowOS is running:  http://localhost:8765
echo   Keep this window open. Close it to stop WorkFlowOS.
echo   Real observation: double-click run_agent.bat
echo   Browser observation: Chrome - Extensions - Developer mode - Load unpacked - the "extension" folder
echo.
start "" cmd /c "timeout /t 5 >nul & start "" http://localhost:8765"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
