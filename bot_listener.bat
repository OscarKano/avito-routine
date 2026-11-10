@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\bot_listener.py
pause
