from __future__ import annotations

from dataclasses import dataclass
import json
import io
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from .definitions import KeybindDefinition, ScriptDefinition, TimingDefinition
from .updater import scripts_cache_dir, scripts_json_cache_path


@dataclass(slots=True)
class LaunchResult:
    ok: bool
    message: str
    process: subprocess.Popen[str] | None = None


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def resources_root() -> Path:
    return project_root() / "resources"


def managed_runtime_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / "OffLimits" / "AFK"


def keybind_settings_path() -> Path:
    return managed_runtime_dir() / "keybinds.json"


def resolve_entry(entry: str) -> Path:
    entry_path = Path(entry)
    if entry_path.is_absolute():
        return entry_path

    cache_path = scripts_cache_dir() / entry_path.name
    if cache_path.exists():
        return cache_path

    resource_path = resources_root() / entry_path
    if resource_path.exists():
        return resource_path

    project_path = project_root() / entry_path
    if project_path.exists():
        return project_path

    return resource_path


def active_scripts_json_path() -> Path:
    cached = scripts_json_cache_path()
    if cached.exists():
        return cached
    return resources_root() / "scripts.json"


def _find_ahk_runtime() -> Path | None:
    managed_candidates = [
        managed_runtime_dir() / "AutoHotkey64.exe",
        managed_runtime_dir() / "AutoHotkey.exe",
    ]
    for candidate in managed_candidates:
        if candidate.exists():
            return candidate

    path_candidates = [
        shutil.which("AutoHotkey64.exe"),
        shutil.which("AutoHotkey.exe"),
        shutil.which("AutoHotkeyU64.exe"),
        shutil.which("AutoHotkeyU32.exe"),
    ]
    for candidate in path_candidates:
        if candidate:
            return Path(candidate)

    common_paths = [
        Path("C:/Program Files/AutoHotkey/v2/AutoHotkey64.exe"),
        Path("C:/Program Files/AutoHotkey/v2/AutoHotkey.exe"),
        Path("C:/Program Files/AutoHotkey/AutoHotkey64.exe"),
        Path("C:/Program Files/AutoHotkey/v1.1.37.02/AutoHotkeyU64.exe"),
        Path("C:/Program Files/AutoHotkey/v1.1.37.02/AutoHotkeyU32.exe"),
        Path("C:/Program Files/AutoHotkey/AutoHotkeyU64.exe"),
        Path("C:/Program Files/AutoHotkey/AutoHotkeyU32.exe"),
    ]

    for candidate in common_paths:
        if candidate.exists():
            return candidate

    return None


def _download_managed_ahk_runtime() -> Path:
    runtime_dir = managed_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)

    metadata_url = "https://api.github.com/repos/AutoHotkey/AutoHotkey/releases/latest"
    request = urllib.request.Request(
        metadata_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OffLimitsAFKLauncher",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)

    assets = release.get("assets", [])
    zip_asset = next(
        (
            asset
            for asset in assets
            if asset.get("name", "").startswith("AutoHotkey_") and asset.get("name", "").endswith(".zip")
        ),
        None,
    )
    if zip_asset is None:
        raise FileNotFoundError("Could not find official AutoHotkey zip asset in latest GitHub release.")

    download_url = zip_asset["browser_download_url"]
    zip_request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "OffLimitsAFKLauncher"},
    )
    with urllib.request.urlopen(zip_request, timeout=60) as response:
        archive_bytes = response.read()

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        candidates = [name for name in archive.namelist() if name.endswith("AutoHotkey64.exe")]
        if not candidates:
            raise FileNotFoundError("Downloaded AutoHotkey zip did not contain AutoHotkey64.exe.")
        member = candidates[0]
        target = runtime_dir / "AutoHotkey64.exe"
        with archive.open(member) as source, target.open("wb") as dest:
            shutil.copyfileobj(source, dest)
    return target


def ensure_ahk_runtime() -> Path:
    existing = _find_ahk_runtime()
    if existing is not None:
        return existing
    return _download_managed_ahk_runtime()


def current_ahk_runtime_label() -> str:
    runtime = _find_ahk_runtime()
    if runtime is None:
        return "AHK v2 (download on launch)"

    lowered = str(runtime).lower()
    if "v1.1" in lowered or "autohotkeyu64" in lowered or "autohotkeyu32" in lowered:
        return "AHK v1"
    if "v2" in lowered or "autohotkey64.exe" in lowered or lowered.endswith("autohotkey.exe"):
        return "AHK v2"
    return f"AHK: {runtime.name}"


def normalize_keybind_value(value: str) -> str:
    candidate = str(value).strip()
    if not candidate:
        return ""

    runtime = ensure_ahk_runtime()
    helper_source = """#Requires AutoHotkey v2.0
value := Trim(A_Args[1])
cleaned := Trim(value, " {}()")

if (value = "") {
    FileAppend("", "*")
    ExitApp()
}

if RegExMatch(cleaned, "i)^sc[0-9a-f]+$") {
    FileAppend("sc" . StrLower(SubStr(cleaned, 3)), "*")
    ExitApp()
}

if RegExMatch(cleaned, "i)^vk[0-9a-f]+$") {
    FileAppend("vk" . StrLower(SubStr(cleaned, 3)), "*")
    ExitApp()
}

if (StrLen(value) = 1) {
    sc := GetKeySC(value)
    if sc && !RegExMatch(value, "^[A-Za-z0-9]$") {
        FileAppend(StrLower(Format("sc{:03X}", sc)), "*")
        ExitApp()
    }
}

canonical := ""
try canonical := GetKeyName(value)
if (canonical = "" && cleaned != value)
    try canonical := GetKeyName(cleaned)

if (canonical != "") {
    FileAppend(canonical, "*")
    ExitApp()
}

FileAppend(value, "*")
"""

    with tempfile.NamedTemporaryFile("w", suffix=".ahk", delete=False, encoding="utf-8") as helper_file:
        helper_file.write(helper_source)
        helper_path = Path(helper_file.name)

    try:
        result = subprocess.run(
            [str(runtime), str(helper_path), candidate],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        helper_path.unlink(missing_ok=True)
        return candidate

    helper_path.unlink(missing_ok=True)
    normalized = result.stdout.strip()
    return normalized or candidate


def format_keybind_display(value: str) -> str:
    candidate = str(value).strip()
    if not candidate:
        return ""

    runtime = ensure_ahk_runtime()
    helper_source = """#Requires AutoHotkey v2.0
value := Trim(A_Args[1])
cleaned := Trim(value, " {}()")

if (value = "") {
    FileAppend("", "*")
    ExitApp()
}

display := ""
try display := GetKeyName(cleaned)
if (display = "")
    try display := GetKeyName(value)

if (display = "")
    display := value

FileAppend(display, "*")
"""

    with tempfile.NamedTemporaryFile("w", suffix=".ahk", delete=False, encoding="utf-8") as helper_file:
        helper_file.write(helper_source)
        helper_path = Path(helper_file.name)

    try:
        result = subprocess.run(
            [str(runtime), str(helper_path), candidate],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        helper_path.unlink(missing_ok=True)
        return candidate.upper()

    helper_path.unlink(missing_ok=True)
    display = result.stdout.strip() or candidate
    return display.upper()


def _materialize_if_frozen(source: Path) -> Path:
    if not getattr(sys, "frozen", False):
        return source

    target_dir = Path(tempfile.mkdtemp(prefix="script_host_"))
    target = target_dir / source.name
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _build_flag_args(definitions: list[TimingDefinition | KeybindDefinition], overrides: dict[str, str] | None) -> list[str]:
    args: list[str] = []
    overrides = overrides or {}

    for item in definitions:
        value = str(overrides.get(item.key, item.value)).strip()
        if not value:
            continue
        args.extend([item.flag, value])

    return args


def build_command(
    definition: ScriptDefinition,
    option_overrides: dict[str, str] | None = None,
) -> list[str]:
    entry = resolve_entry(definition.entry)
    option_args = _build_flag_args(definition.timings + definition.keybinds, option_overrides)

    if definition.kind == "python":
        return [sys.executable, str(entry), *definition.args, *option_args]

    if definition.kind == "ahk":
        runtime = ensure_ahk_runtime()
        script_path = _materialize_if_frozen(entry)
        return [str(runtime), str(script_path), *definition.args, *option_args]

    raise ValueError(f"Unsupported script kind: {definition.kind}")


def launch_script(
    definition: ScriptDefinition,
    option_overrides: dict[str, str] | None = None,
) -> LaunchResult:
    try:
        command = build_command(definition, option_overrides)
        cwd = str(resources_root())
        process = subprocess.Popen(command, cwd=cwd)
    except Exception as exc:  # noqa: BLE001
        return LaunchResult(False, str(exc))

    return LaunchResult(True, f"Started: {definition.name}", process=process)


def stop_process(process: subprocess.Popen[str] | None) -> LaunchResult:
    if process is None or process.poll() is not None:
        return LaunchResult(False, "No running script to stop.")

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            process.terminate()
            process.wait(timeout=5)
    except Exception as exc:  # noqa: BLE001
        return LaunchResult(False, f"Failed to stop script: {exc}")

    return LaunchResult(True, "Stopped script.")
