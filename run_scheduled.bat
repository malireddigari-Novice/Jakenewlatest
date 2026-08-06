@echo off
REM Launched by Task Scheduler (Jakenew_DailyRun) at 08:10 CST each weekday.
REM PYTHONUTF8 keeps non-cp1252 log glyphs from crashing logging on the console.
REM Full python path so it works regardless of the scheduled task's PATH.
set PYTHONUTF8=1
cd /d "%~dp0"
"C:\Python314\python.exe" main.py >> jakenew_scheduled.log 2>&1
