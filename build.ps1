$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$importDir = Join-Path $root "resources\\imported"
if (Test-Path $importDir) {
  Remove-Item $importDir -Recurse -Force
}
New-Item -ItemType Directory -Path $importDir | Out-Null

Get-ChildItem -Path $root -Filter *.ahk -File | ForEach-Object {
  Copy-Item $_.FullName -Destination (Join-Path $importDir $_.Name)
}

$runtimePath = Join-Path $root "resources\\vendor\\AutoHotkey64.exe"
if (-not (Test-Path $runtimePath)) {
  Write-Warning "Bundled AutoHotkey runtime not found at resources\\vendor\\AutoHotkey64.exe. AHK scripts will require a local AutoHotkey install unless you add that file before building."
}

python -m pip install --upgrade pyinstaller
python -m PyInstaller `
  --noconfirm `
  --onefile `
  --windowed `
  --name ScriptHost `
  --add-data "resources;resources" `
  main.py
