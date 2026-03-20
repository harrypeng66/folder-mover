@echo off
cd /d "%~dp0"
if exist folder_mover.exe (
  start "" /wait folder_mover.exe
) else (
  py -3 folder_mover.py
  if errorlevel 1 (
    python folder_mover.py
  )
)
