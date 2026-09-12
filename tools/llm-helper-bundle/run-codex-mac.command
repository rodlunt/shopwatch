#!/bin/bash
cd "$(dirname "$0")"
URL=$(cat shopwatch-url.txt)
python3 llm-helper.py --url "$URL" --backend codex
echo
read -p "Press Enter to close this window..."
