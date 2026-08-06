@echo off
REM Launch the Jakenew Attention Engine. PYTHONUTF8 keeps non-cp1252 log glyphs from
REM crashing logging on the Windows console.
set PYTHONUTF8=1
cd /d "%~dp0"
python main.py
