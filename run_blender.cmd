@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_blender.ps1" %*
exit /b %ERRORLEVEL%
