@echo off
title Remove Narrative Radar 24/7
schtasks /delete /tn "Narrative Radar" /f
echo.
echo The Radar will no longer start by itself. You can still start it with "Start Narrative Radar.bat".
echo.
pause
