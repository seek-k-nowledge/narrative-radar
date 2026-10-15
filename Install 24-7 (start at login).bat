@echo off
title Install Narrative Radar 24/7
cd /d "%~dp0"
echo This makes the Narrative Radar start by itself every time you log in to Windows.
echo.
schtasks /create /tn "Narrative Radar" /tr "cmd /c start \"Narrative Radar\" /min \"%~dp0Start Narrative Radar.bat\"" /sc onlogon /f
if errorlevel 1 (
  echo.
  echo That did not work. Right-click this file and choose "Run as administrator", then try again.
) else (
  echo.
  echo Done. From now on the Radar starts on its own when you log in.
  echo Open it any time at http://localhost:8765
  echo To undo this, double-click "Remove 24-7.bat".
)
echo.
pause
