@echo off
setlocal
cd /d "%~dp0"

echo ===============================
echo   CET Agent
echo   http://127.0.0.1:8000/
echo   Ctrl+C to stop
echo ===============================
echo.

REM Open the browser 4s later in a hidden helper window, then run the server.
REM start /b would keep the timer console visible; /min tucks it away.
start "" /min cmd /c "timeout /t 4 /nobreak >NUL && start http://127.0.0.1:8000/"

uv run python -m backend.main

REM If the server crashed before Ctrl+C, keep the window open so the user
REM can read the traceback.
if errorlevel 1 (
  echo.
  echo Server exited with error. Press any key to close.
  pause >NUL
)
endlocal
