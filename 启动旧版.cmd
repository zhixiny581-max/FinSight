@echo off
chcp 65001 >nul
node "%~dp0tools\launch.cjs" legacy %*
if errorlevel 1 pause
