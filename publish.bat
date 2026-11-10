@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
python scripts\publish_to_telegram.py %*
echo.
pause
