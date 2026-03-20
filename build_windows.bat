@echo off
cd /d "%~dp0"
py -3 -m pip install pyinstaller
if errorlevel 1 (
  python -m pip install pyinstaller
)
py -3 -m PyInstaller --onefile --noconsole --name folder_mover folder_mover.py
if errorlevel 1 (
  python -m PyInstaller --onefile --noconsole --name folder_mover folder_mover.py
)
