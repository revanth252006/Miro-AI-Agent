@echo off
title Miro AI Assistant
cd /d "D:\Unified_AI_Assistant"

:: FORCE ACTIVATION OF VENV (Fixes the crash)
call venv\Scripts\activate

:: RUN THE BRIDGE SERVER
python main.py

pause