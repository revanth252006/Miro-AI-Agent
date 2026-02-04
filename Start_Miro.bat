@echo off
title Miro AI Assistant
cd /d "D:\Unified_AI_Assistant"

:: --- IMPORTANT: Activate the Virtual Environment ---
:: This ensures we use the Python version where we fixed the bugs
call venv\Scripts\activate

echo Starting Miro Agent in Background...
echo You can now close VS Code.
echo Say "Hey Miro" to activate.

:: Run the AI
python main.py

:: Keep window open if it crashes so we can see why
pause