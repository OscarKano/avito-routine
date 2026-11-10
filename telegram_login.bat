@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
echo.
python scripts\telegram_login.py
echo.
pause
