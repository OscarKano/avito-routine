@echo off
cd /d "%~dp0"
echo Устанавливаю нужные библиотеки (один раз, может занять минуту)...
python -m pip install -r requirements.txt --quiet
echo.
echo Скачиваю браузер Chromium, если его ещё нет (один раз, ~250 МБ, может занять пару минут)...
python -m playwright install chrome
echo.
echo Запускаю диагностику...
echo.
python scripts\test_playwright_fetch.py
echo.
pause
