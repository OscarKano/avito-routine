@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
echo.
echo Скачиваю ТЕКСТ постов из каналов поставщиков (без фото - так быстрее).
echo.
python scripts\telegram_export_suppliers.py
echo.
pause
