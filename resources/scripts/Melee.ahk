#Requires AutoHotkey v2.0
#SingleInstance Force
#MaxThreadsPerHotkey 2
#MaxThreads 3

SendMode("Input")
SetKeyDelay(-1, -1)
DllCall("winmm\timeBeginPeriod", "UInt", 1)

global Toggle := false
global TargetWindowTitle := "ahk_exe cod.exe"
global MarkerFilePath := ""
global VDelay := 130
global VDelayRnd := 79
global ScoreboardToggling := 1
global ToggleKey := "8"
global ExitKey := "F2"
global ScoreboardKey := "sc029"
global MeleeKey := "v"

ApplyOverrides()
ConfigureHotkeys()
WriteMarker("READY")

ApplyOverrides() {
    global TargetWindowTitle, MarkerFilePath, VDelay, VDelayRnd, ScoreboardToggling, ToggleKey, ExitKey, ScoreboardKey, MeleeKey

    TargetWindowTitle := ReadStringArg("--target-title", TargetWindowTitle)
    MarkerFilePath := ReadStringArg("--marker-file", MarkerFilePath)
    VDelay := ReadIntArg("--v-delay", VDelay)
    VDelayRnd := ReadIntArg("--v-delay-random", VDelayRnd)
    ScoreboardToggling := ReadIntArg("--scoreboard-toggling", ScoreboardToggling)
    ToggleKey := NormalizeKeyName(ReadStringArg("--toggle-key", ToggleKey))
    ExitKey := NormalizeKeyName(ReadStringArg("--exit-key", ExitKey))
    ScoreboardKey := NormalizeKeyName(ReadStringArg("--scoreboard-key", ScoreboardKey))
    MeleeKey := NormalizeKeyName(ReadStringArg("--melee-key", MeleeKey))
}

ConfigureHotkeys() {
    global TargetWindowTitle, ToggleKey, ExitKey

    HotIfWinActive(TargetWindowTitle)
    Hotkey(ToggleKey, ToggleScript)
    Hotkey(ExitKey, ExitScript)
    HotIf()
}

ReadIntArg(flag, fallback) {
    loop A_Args.Length {
        if (A_Args[A_Index] = flag) && (A_Index < A_Args.Length) {
            value := Integer(A_Args[A_Index + 1])
            return value >= 0 ? value : fallback
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

WriteMarker(event) {
    global MarkerFilePath
    if MarkerFilePath = "" {
        return
    }
    try FileAppend(event . "`n", MarkerFilePath, "UTF-8")
}

ToggleScript(*) {
    global Toggle

    Toggle := !Toggle
    if Toggle {
        WriteMarker("START")
        ShowStatus("ON")
        SetTimer(MainLoop, -1)
    } else {
        WriteMarker("END")
        ShowStatus("OFF")
        SetTimer(MainLoop, 0)
        Sleep(1000)
        Reload()
    }
}

ExitScript(*) {
    WriteMarker("EXIT")
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
    global Toggle, VDelay, VDelayRnd, ScoreboardToggling, ScoreboardKey, MeleeKey

    if !Toggle {
        return
    }
    if ScoreboardToggling {
        Sleep(10)
        SendKey(ScoreboardKey)
    }
    SendKey(MeleeKey)
    jitter := Random(0, VDelayRnd)
    SetTimer(MainLoop, -(VDelay + jitter))
}
