@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "FINSIGHT_EXIT=%ERRORLEVEL%"
if not "%FINSIGHT_EXIT%"=="0" pause
exit /b %FINSIGHT_EXIT%
