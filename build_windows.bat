@echo off
cd /d "%~dp0"
if exist requirements.txt (
  py -3 -m pip install -r requirements.txt
  if errorlevel 1 (
    python -m pip install -r requirements.txt
  )
)

py -3 -m pip install pyinstaller
if errorlevel 1 (
  python -m pip install pyinstaller
)

py -3 -m PyInstaller --clean --onefile --noconsole --name material_image_name_cleaner material_image_name_cleaner.py
if errorlevel 1 (
  python -m PyInstaller --clean --onefile --noconsole --name material_image_name_cleaner material_image_name_cleaner.py
)
