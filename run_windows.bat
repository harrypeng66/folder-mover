@echo off
cd /d "%~dp0"
if exist material_image_name_cleaner.exe (
  start "" /wait material_image_name_cleaner.exe
) else (
  py -3 material_image_name_cleaner.py
  if errorlevel 1 (
    python material_image_name_cleaner.py
  )
)
