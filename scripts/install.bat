@echo off
:: Lyra AI Platform — Windows Installer
:: Copyright (C) 2026 Lyra Contributors — All Rights Reserved. See LICENSE.
echo.
echo   Lyra AI Platform - Windows Installer
echo   =====================================
SET LYRA_DIR=%~dp0..
SET VENV=%LYRA_DIR%\.venv
IF NOT EXIST "%VENV%" python -m venv "%VENV%"
SET PIP=%VENV%\Scripts\pip
%PIP% install --upgrade pip -q
%PIP% install -r "%LYRA_DIR%\requirements.txt" -q
mkdir "%LYRA_DIR%\data\models" 2>nul
mkdir "%LYRA_DIR%\data\uploads" 2>nul
mkdir "%LYRA_DIR%\data\memory" 2>nul
mkdir "%LYRA_DIR%\data\logs" 2>nul
for %%d in (lyra lyra\api lyra\core lyra\models lyra\memory lyra\search lyra\telemetry lyra\plugins) do (
  type nul > "%LYRA_DIR%\%%d\__init__.py"
)
echo.
echo   Installation complete!
echo   Run: scripts\start.bat
echo   Open: http://localhost:7860
echo.
pause
