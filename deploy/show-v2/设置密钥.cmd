@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python.exe >nul 2>nul
if errorlevel 1 goto :trypy
python -B setup_keys.py
goto :end

:trypy
where py.exe >nul 2>nul
if errorlevel 1 goto :nopy
py -3 -B setup_keys.py
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
echo.
pause
