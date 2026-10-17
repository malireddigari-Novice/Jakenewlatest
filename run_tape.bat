@echo off
REM Tape lane: trade-level options-flow RESEARCH collector (runs beside run.bat; never places orders).
set PYTHONUTF8=1
cd /d "%~dp0"
python tape_main.py
