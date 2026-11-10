@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
python -m playwright install chrome
echo.
python scripts\build_preview.py 5
echo.
pause
