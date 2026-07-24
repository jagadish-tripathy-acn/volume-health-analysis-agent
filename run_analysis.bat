@echo off
echo ============================================================
echo   Volume Health Analysis Agent — Full Analysis Run
echo ============================================================
echo.

cd /d "%~dp0"

echo [Step 1/2] Collecting local drive data + discovering active TC volume...
python collect_volume_data.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] collect_volume_data.py failed. Exiting.
    pause
    exit /b 1
)

echo.
echo [Step 2/2] Analysing volume health + auto-switching if needed...
python check_volume_health.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] check_volume_health.py failed. Exiting.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Analysis Complete. Reports are in the data\ folder:
echo     VOLUME_USAGE_REPORT.txt
echo     OUTPUT_Find_Volume_inUse.txt
echo     OUTPUT_health_report.txt
echo     OUTPUT_switch_log.txt  (if a switch was performed)
echo ============================================================
echo.
pause
