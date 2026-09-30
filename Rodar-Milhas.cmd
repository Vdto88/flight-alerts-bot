@echo off
cd /d "%~dp0"
python scripts\local_miles.py --interactive
set "run_result=%errorlevel%"
pause
exit /b %run_result%
