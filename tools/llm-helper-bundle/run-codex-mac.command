#!/bin/bash
cd "$(dirname "$0")"
python3 llm-helper.py --url "__SHOPWATCH_URL__" --backend codex
echo
read -p "Press Enter to close this window..."
