@echo off
:: Lyra AI Platform — Windows Start Script
:: Copyright (C) 2026 Lyra Contributors — All Rights Reserved. See LICENSE.
SET LYRA_DIR=%~dp0..
SET PYTHON=%LYRA_DIR%\.venv\Scripts\python
echo.
echo   Lyra AI Platform  ^|  http://127.0.0.1:7860
echo.
cd /d "%LYRA_DIR%"
%PYTHON% -m uvicorn lyra.main:app --host 127.0.0.1 --port 7860
pause
