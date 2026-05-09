@echo off
cd /d "%~dp0"
if exist build_resources rmdir /s /q build_resources
mkdir build_resources
copy /Y resources\scripts.json build_resources\scripts.json >nul
copy /Y resources\loadout.json build_resources\loadout.json >nul
xcopy resources\pictures build_resources\pictures /E /I /Y >nul
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name ScriptHost --distpath . --add-data "build_resources;resources" main.py
if errorlevel 1 goto :cleanup_fail

if exist build rmdir /s /q build
if exist build_resources rmdir /s /q build_resources
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
if exist ScriptHost.spec del /q ScriptHost.spec
goto :eof

:cleanup_fail
if exist build_resources rmdir /s /q build_resources
