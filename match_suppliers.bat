@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
python scripts\match_avito_to_suppliers.py
echo.
pause
