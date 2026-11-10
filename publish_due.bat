@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\publish_due.py --send >> logs\publish_due.log 2>&1
