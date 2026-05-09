# Script Host

One Windows `.exe` that launches many helper scripts from one GUI.

## Why this shape

- Python host app gives stable GUI and packaging flow.
- AHK scripts stay AHK for the actual automation layer.
- One config file controls what appears in GUI.
- Root-level `.ahk` files auto-appear in dev.
- `PyInstaller --onefile` builds single `ScriptHost.exe`.
- Launcher auto-downloads script files from GitHub into `%APPDATA%\OffLimits\AFK\scripts` and loads them from there.
- Launcher auto-downloads the official runtime into `%APPDATA%\OffLimits\AFK` when needed, and can also use an already installed system runtime.

## Project layout

- `main.py`: app entry point.
- `app/`: GUI, config loading, runtime launching.
- `resources/scripts.json`: list of scripts shown in GUI.
- `resources/loadout.json`: shared required perks and augments shown for all scripts.
- `resources/scripts/`: dev copy of AHK automation scripts used as GitHub source.

## Run in dev

```powershell
python main.py
```

## Build one exe

```powershell
.\build.ps1
```

Build output lands in `dist/ScriptHost.exe`.

## Add script

1. Put script file in `resources/scripts/`.
2. Add entry in `resources/scripts.json`.
3. Push repo update so launcher can download new file.
4. Rebuild app only if GUI/assets changed.

Example config item:

```json
{
  "id": "my-tool",
  "name": "My Tool",
  "kind": "python",
  "entry": "scripts/my_tool.py",
  "description": "Does useful work.",
  "args": [],
  "setup": ["Do this first"],
  "accent": "#8b5cf6"
}
```

Shared loadout example:

```json
{
  "perks": [
    {
      "name": "Jugger-Nog",
      "image": "pictures/Jugger-Nog.png",
      "augments": [
        {"slot": "Major", "name": "Probiotic", "image": "pictures/Jugger-Nog Major Probiotic.png"},
        {"slot": "Minor", "name": "Durable Plates", "image": "pictures/Jugger-Nog Minor Durable Plates.png"},
        {"slot": "Minor", "name": "Hardened Plates", "image": "pictures/Jugger-Nog Minor Hardened Plates.png"}
      ]
    }
  ]
}
```

For AutoHotkey:

- Set `"kind": "ahk"`.
- Use AHK v2 syntax.
- Launcher can auto-download the official AutoHotkey zip from GitHub, extract `AutoHotkey64.exe`, and cache it in `%APPDATA%\OffLimits\AFK`.
- If AutoHotkey is already installed on the machine, the launcher can use that too.
- Built `.exe` does not bundle `.ahk` files. On startup or launch, it syncs `resources/scripts/*.ahk` from GitHub into `%APPDATA%\OffLimits\AFK\scripts` and runs cached copies from there.
- For private repos, set `OFFLIMITS_GITHUB_TOKEN` or `GITHUB_TOKEN`, or place a personal access token in `%APPDATA%\OffLimits\AFK\github_token.txt`.
- Any `.ahk` file in project root is auto-detected in dev.

## Recommendation

Keep the launcher in Python and keep the real automation scripts in AHK.

This project now treats AHK as the source of truth for the actual game macros, while Python handles:

- GUI
- process launching and stopping
- packaging
- shared config and assets
