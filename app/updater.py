from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .version import APP_VERSION


GITHUB_REPO = "Lorenso0/OffLimitsAFK"
GITHUB_BRANCH = "main"
_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}"


def _raw_repo_url(relative_path: str) -> str:
    normalized = relative_path.strip().replace("\\", "/")
    quoted = "/".join(urllib.parse.quote(part) for part in normalized.split("/"))
    return f"{_RAW_BASE}/{quoted}"


@dataclass(slots=True)
class SyncResult:
    ok: bool
    updated: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    app_update_available: bool = False
    latest_version: str = ""
    current_version: str = APP_VERSION
    release_url: str = ""
    version_error: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.updated or self.new)

    def summary(self) -> str:
        if self.errors and not self.changed:
            return f"Update check failed: {self.errors[0]}"
        parts: list[str] = []
        if self.new:
            parts.append(f"{len(self.new)} new script{'s' if len(self.new) != 1 else ''}")
        if self.updated:
            parts.append(f"{len(self.updated)} updated")
        if parts:
            return "Scripts updated: " + ", ".join(parts)
        return "Scripts up to date"


def _version_parts(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV")
    if not cleaned:
        return ()
    parts: list[int] = []
    for piece in cleaned.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _is_newer_version(latest: str, current: str) -> bool:
    latest_parts = _version_parts(latest)
    current_parts = _version_parts(current)
    if not latest_parts or not current_parts:
        return False
    width = max(len(latest_parts), len(current_parts))
    latest_full = latest_parts + (0,) * (width - len(latest_parts))
    current_full = current_parts + (0,) * (width - len(current_parts))
    return latest_full > current_full


def _appdata_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / "OffLimits" / "AFK"


def scripts_cache_dir() -> Path:
    return _appdata_dir() / "scripts"


def scripts_json_cache_path() -> Path:
    return _appdata_dir() / "scripts.json"


def _request_headers(accept: str | None = None) -> dict[str, str]:
    headers = {"User-Agent": "OffLimitsAFKLauncher"}
    if accept:
        headers["Accept"] = accept

    return headers


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers=_request_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _download_text(url: str) -> str:
    return _download_bytes(url).decode("utf-8")


def _write_if_changed(dest: Path, content: bytes, key: str, result: SyncResult) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    existed = dest.exists()
    current = dest.read_bytes() if existed else b""
    if current == content:
        return
    dest.write_bytes(content)
    (result.new if not existed else result.updated).append(key)


def check_app_version() -> tuple[bool, str, str]:
    try:
        version_text = _download_text(_raw_repo_url("app/version.py"))
    except Exception:
        return False, "", ""

    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', version_text)
    if not match:
        return False, "", ""

    latest_version = match.group(1).strip()
    release_url = f"https://github.com/{GITHUB_REPO}/releases"
    return _is_newer_version(latest_version, APP_VERSION), latest_version, release_url


def sync_scripts() -> SyncResult:
    result = SyncResult(ok=False)
    try:
        try:
            scripts_json_bytes = _download_bytes(_raw_repo_url("resources/scripts.json"))
            _write_if_changed(scripts_json_cache_path(), scripts_json_bytes, "scripts.json", result)
            raw_config = json.loads(scripts_json_bytes.decode("utf-8"))
        except Exception as exc:
            result.errors.append(f"scripts.json: {exc}")
            raw_config = {"scripts": []}

        for item in raw_config.get("scripts", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("kind", "")).strip().lower() != "ahk":
                continue

            entry = str(item.get("entry", "")).strip()
            if not entry.startswith("scripts/"):
                continue

            name = Path(entry).name
            raw_url = _raw_repo_url(f"resources/{entry}")
            try:
                script_bytes = _download_bytes(raw_url)
                _write_if_changed(scripts_cache_dir() / name, script_bytes, name, result)
            except Exception as exc:
                result.errors.append(f"{name}: {exc}")

        try:
            update_available, latest_version, release_url = check_app_version()
            result.app_update_available = update_available
            result.latest_version = latest_version
            result.release_url = release_url
        except Exception as exc:
            result.version_error = str(exc)

        result.ok = not result.errors

    except Exception as exc:
        result.errors.append(str(exc))

    return result
