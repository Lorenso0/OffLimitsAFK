#Requires AutoHotkey v2.0
#MaxThreadsPerHotkey 2
#HotIf WinActive("ahk_exe cod.exe")

SendMode("Input")
SetKeyDelay(-1, -1)

global Toggle := false
global ResetTime := 550
global VWaitTime := 1600
global ScoreboardToggling := 1
global ToggleKey := "8"
global ExitKey := "F2"
global LethalKey := "g"
global WeaponSwitchKey := "1"
global ScoreboardKey := "sc029"
global MeleeKey := "v"

ApplyOverrides()
ConfigureHotkeys()
ShowStatus("LOADED")

ApplyOverrides() {
    global ResetTime, VWaitTime, ScoreboardToggling, ToggleKey, ExitKey, LethalKey, WeaponSwitchKey, ScoreboardKey, MeleeKey

    ResetTime := ReadIntArg("--reset-time", ResetTime)
    VWaitTime := ReadIntArg("--v-wait-time", VWaitTime)
    ScoreboardToggling := ReadIntArg("--scoreboard-toggling", ScoreboardToggling)
    ToggleKey := NormalizeKeyName(ReadStringArg("--toggle-key", ToggleKey))
    ExitKey := NormalizeKeyName(ReadStringArg("--exit-key", ExitKey))
    LethalKey := NormalizeKeyName(ReadStringArg("--lethal-key", LethalKey))
    WeaponSwitchKey := NormalizeKeyName(ReadStringArg("--weapon-switch-key", WeaponSwitchKey))
    ScoreboardKey := NormalizeKeyName(ReadStringArg("--scoreboard-key", ScoreboardKey))
    MeleeKey := NormalizeKeyName(ReadStringArg("--melee-key", MeleeKey))
}

ConfigureHotkeys() {
    global ToggleKey, ExitKey

    HotIfWinActive("ahk_exe cod.exe")
    Hotkey(ToggleKey, ToggleScript)
    Hotkey(ExitKey, ExitScript)
    HotIf()
}

ReadIntArg(flag, fallback) {
    loop A_Args.Length {
        if (A_Args[A_Index] = flag) && (A_Index < A_Args.Length) {
            value := Integer(A_Args[A_Index + 1])
            return value > 0 ? value : fallback
        }
    }
    return fallback
}

ReadStringArg(flag, fallback) {
    loop A_Args.Length {
        if (A_Args[A_Index] = flag) && (A_Index < A_Args.Length) {
            value := Trim(A_Args[A_Index + 1])
            return value != "" ? value : fallback
        }
    }
    return fallback
}

NormalizeKeyName(value) {
    cleaned := Trim(value, " `t`r`n{}()")
    if cleaned = "" {
        return value
    }
    if RegExMatch(cleaned, "i)^(sc|vk)[0-9a-f]+$") {
        return StrLower(cleaned)
    }
    return cleaned
}

FormatSendKey(value) {
    return StrLen(value) = 1 ? value : "{" value "}"
}

SendKey(value) {
    Send(FormatSendKey(value))
}

ToggleScript(*) {
    global Toggle

    Toggle := !Toggle
    if Toggle {
        ShowStatus("ON")
        SetTimer(MainLoop, -1)
    } else {
        ShowStatus("OFF")
        Sleep(1000)
        Reload()
    }
}

ExitScript(*) {
    ExitApp()
}

ShowStatus(state) {
    MouseGetPos(&mx, &my)
    ToolTip("SCRIPT " state, 0, 0, 1)
    ToolTip("SCRIPT " state, mx + 18, my + 22, 2)
    SetTimer(ClearCursorPopup, -900)
}

ClearCursorPopup() {
    ToolTip(, , , 2)
}

MainLoop() {
    global Toggle, ResetTime, VWaitTime, ScoreboardToggling, LethalKey, WeaponSwitchKey, ScoreboardKey, MeleeKey

    loop {
        if !Toggle {
            break
        }

        Send("{LButton down}")
        Sleep(60)
        Send("{LButton up}")
        Sleep(40)
        SendKey(LethalKey)
        Sleep(60)
        SendKey(WeaponSwitchKey)
        if ScoreboardToggling {
            Sleep(10)
            SendKey(ScoreboardKey)
        }
        Sleep(ResetTime)

        if ScoreboardToggling {
            SendKey(ScoreboardKey)
            Sleep(10)
        }
        SendKey(MeleeKey)
        Sleep(VWaitTime)
    }
}
