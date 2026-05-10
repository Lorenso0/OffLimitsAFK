@echo off
cd /d "%~dp0"
if exist build_resources rmdir /s /q build_resources
mkdir build_resources
copy /Y resources\scripts.json build_resources\scripts.json >nul
copy /Y resources\loadout.json build_resources\loadout.json >nul
xcopy resources\pictures build_resources\pictures /E /I /Y >nul
python -m pip install --upgrade pyinstaller pillow
python -c "from PIL import Image; Image.open(r'resources\pictures\appicon.png').save(r'build_resources\appicon.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
if errorlevel 1 goto :cleanup_fail
python -m PyInstaller --noconfirm --onefile --windowed --name "Off Limits AFK" --distpath . --icon "build_resources\appicon.ico" --add-data "build_resources;resources" main.py
if errorlevel 1 goto :cleanup_fail

if exist build rmdir /s /q build
if exist build_resources rmdir /s /q build_resources
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
if exist "Off Limits AFK.spec" del /q "Off Limits AFK.spec"
goto :eof

:cleanup_fail
if exist build_resources rmdir /s /q build_resources
