@echo off
title Capture Agent Bot
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python bot.py
pause
