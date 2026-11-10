@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\check_yandex_disk.py
pause
