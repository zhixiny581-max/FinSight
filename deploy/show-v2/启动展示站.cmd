@echo off
cd /d "%~dp0"
where python.exe >nul 2>nul
if errorlevel 1 goto :trypy
python -B run_local.py %1
goto :end

:trypy
where py.exe >nul 2>nul
if errorlevel 1 goto :nopy
py -3 -B run_local.py %1
goto :end

:nopy
echo.
echo   [ERROR] Python not found / Python not runnable.
echo   Install Python 3 from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup.
echo.
pause
exit /b 1

:end
pause
