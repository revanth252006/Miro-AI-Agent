@echo off
title Miro AI Launcher
echo 🚀 Awakening Miro...

:: --- 1. Navigate to the correct folder ---
cd /d "D:\Unified_AI_Assistant"

:: --- 2. Start the Python Brain (Hidden/Minimized) ---
echo Starting Brain...
start /min "Miro Brain" cmd /k "call venv\Scripts\activate && python main.py"

:: --- 3. Start the Frontend Interface ---
echo Starting Interface...
npm run electron

:: --- 4. Close this launcher window when done ---
exit