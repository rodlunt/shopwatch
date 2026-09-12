Shopwatch LLM Helper
====================

This lets Shopwatch's "Suggest models" button ask a real AI model for help,
using an AI tool you already have on this computer - Claude Code or Codex.
Nothing here needs a password saved anywhere except your own Shopwatch
login, entered once when you start it.

BEFORE YOU START

You need ONE of these already installed and signed in on this computer:
  - Claude Code (claude.ai/code) - the "claude" command
  - OpenAI Codex CLI - the "codex" command

You also need Python 3 installed. Most Macs already have it. On Windows,
if double-clicking the launcher does nothing or shows a "python not
found" error, install Python from https://python.org (tick "Add to PATH"
during setup) and try again.

HOW TO RUN IT

Pick the file that matches your computer AND the AI tool you have:

  Windows + Claude Code:  run-claude-windows.bat
  Windows + Codex:        run-codex-windows.bat
  Mac + Claude Code:      run-claude-mac.command
  Mac + Codex:            run-codex-mac.command
  Linux + Claude Code:    run-claude-linux.sh
  Linux + Codex:          run-codex-linux.sh

Double-click it. A window opens and asks for your Shopwatch username and
password - the same ones you use to open the site in a browser. Leave
that window open while you use the wizard's "Suggest models" button;
close it whenever you're done, and reopen it any time you want the
feature again.

QUESTIONS THIS ANSWERS

"Does this cost me anything?"
  No API key, no bill from Shopwatch. It uses whichever AI subscription
  you already have through Claude Code or Codex.

"Is my password safe?"
  It's sent directly to your own Shopwatch site, the same way your
  browser already sends it. Nothing is saved to disk.

"What does it actually do?"
  It watches for "please suggest a model for X" requests from the
  wizard, asks your AI tool the question, and sends the answer back.
  It does nothing else and touches nothing else on your computer.

"Can I just run the script myself instead?"
  Yes - llm-helper.py in this folder is a normal Python script. Run
  "python3 llm-helper.py --help" to see every option.
