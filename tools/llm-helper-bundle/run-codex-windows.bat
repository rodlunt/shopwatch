@echo off
cd /d "%~dp0"
set /p URL=<shopwatch-url.txt
python llm-helper.py --url "%URL%" --backend codex
echo.
pause
