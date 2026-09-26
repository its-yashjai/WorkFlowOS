@echo off
REM Starts the desktop activity agent (watches app focus + Downloads). No install needed.
cd /d "%~dp0agent"
python wfos_agent.py %*
pause
