@echo off
REM Start LitGraph. Requires: pip install -r requirements.txt
cd /d "%~dp0backend"
python server.py
