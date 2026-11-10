@echo off
cd /d "%~dp0"
echo Устанавливаю нужные библиотеки (один раз, может занять минуту)...
python -m pip install -r requirements.txt --quiet
echo.
echo Запускаю проверку списка объявлений Avito...
echo.
python scripts\check_avito_items.py
echo.
pause
