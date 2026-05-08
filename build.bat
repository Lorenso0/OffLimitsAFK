@echo off
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name ScriptHost --add-data "resources;resources" main.py
