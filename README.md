# Off Limits AFK Scripts

This app is made to help Call of Duty players easily launch AFK scripts from one clean launcher.

Downloads are available [here](https://github.com/Lorenso0/OffLimitsAFK/releases)

![OffLimitsAFK Preview](https://raw.githubusercontent.com/Lorenso0/OffLimitsAFK/refs/heads/main/resources/pictures/AppPreview.png)

You do not need to deal with script files manually. The app is built to keep things simple:

- pick a script
- check the setup shown in the app
- adjust the script variables if needed
- launch the script
- use your toggle key to start or stop it in-game

## What The App Does

- Shows all available AFK scripts in one place
- Lets you edit script timings and options before launch
- Lets you set your keybinds once and reuse them across scripts
- Can test scripts in the built-in `Tester` tab
- Can export supported scripts to GPC
- Checks for script updates from the GitHub repo
- Lets you know if a newer app version is available

## Basic Use

1. Open the app.
2. Click the script selector and choose the script you want.
3. Read the setup and perk requirements shown in the window.
4. Click `Edit Keybinds` and make sure your in-game bindings match.
5. Adjust any script variables if needed.
6. Click `Launch Selected Script`.
7. Go into Call of Duty and press your toggle key to start or stop the script.

## Default Keys

The exact keys can be changed in the app, but the common defaults are:

- Toggle script: `8`
- Exit script: `F2`

## Tester Tab

The `Tester` tab is there so you can test scripts without going straight into the game.

It can:

- open a dedicated tester window
- launch the selected script into that tester window
- show key and mouse input activity
- show the timing between inputs
- show script lifecycle markers like `READY`, `START`, and `END`

This is useful when you want to confirm that a script is firing the right inputs before using it in-game.

## GPC Export

Some scripts support GPC export.

If a script supports it, you can export it from the app and choose your controller platform and button mappings. Scoreboard toggling is not included in GPC exports.

## Updates

The app can:

- download the latest script files from the public GitHub repo
- tell you when a newer app version is available on GitHub

Use the `Sync` button in the app if you want to manually check for updated scripts.

## Important Notes

- Make sure your in-game keybinds match the app keybinds.
- Always read the setup instructions shown for the selected script.
- If a script is already running and you change variables, relaunch it so the new values apply.
- Closing the app will also stop the managed AHK scripts it launched.

## If Something Looks Wrong

If a script is not behaving correctly:

1. Re-check your keybinds in the app.
2. Make sure the game window is focused.
3. Use the `Tester` tab to confirm the script is sending the expected inputs.
4. Relaunch the script after changing any variables.
5. Use `Stop All Scripts` if you want to fully reset the launcher state.

If you still need help, contact me on Discord: `@lorenso0`
