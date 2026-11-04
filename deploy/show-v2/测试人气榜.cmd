@echo off
cd /d "%~dp0"
where python.exe >nul 2>nul
if errorlevel 1 goto :nopy
python -B test_rank.py %*
goto :end

:nopy
echo.
echo   [ERROR] Python not found.
echo   Install Python 3 from https://www.python.org/downloads/
echo.
pause
exit /b 1

:end
pause
