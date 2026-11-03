@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Briefing GitHub Pages Auto Sync Tool
echo ======================================================================
echo    Briefing: GitHub Pages Realtime Auto Sync
echo ======================================================================
echo.
"C:\Users\김영신\.local\bin\python3.15.exe" sync_to_github.py
echo.
pause

