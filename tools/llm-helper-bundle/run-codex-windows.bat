@echo off
cd /d "%~dp0"
python llm-helper.py --url "__SHOPWATCH_URL__" --backend codex
echo.
pause
