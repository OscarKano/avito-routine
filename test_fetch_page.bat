@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
echo.
python scripts\test_fetch_page.py
echo.
pause
