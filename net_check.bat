@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\net_check.py
pause
