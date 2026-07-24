@echo off
echo ============================================================
echo   Volume Health Analysis Agent - Web Dashboard
echo ============================================================
echo.

cd /d "%~dp0"

echo Starting Flask dashboard on http://127.0.0.1:5001 ...
start "" http://127.0.0.1:5001
python -m waitress --port=5001 app.web_runner:app

pause
