@echo off
chcp 65001 >nul
node "%~dp0tools\prepare-release.cjs"
if errorlevel 1 pause
