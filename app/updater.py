from __future__ import annotations

import json
import os
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from .version import APP_VERSION


GITHUB_REPO = "Lorenso0/Off-Limits-AFK"
GITHUB_BRANCH = "main"
_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"
_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}"


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


def _sha_manifest_path() -> Path:
    return _appdata_dir() / "script_shas.json"


def _request_headers(accept: str | None = None) -> dict[str, str]:
    headers = {"User-Agent": "OffLimitsAFKLauncher"}
    if accept:
        headers["Accept"] = accept

    return headers


def _load_sha_manifest() -> dict[str, str]:
    path = _sha_manifest_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_sha_manifest(manifest: dict[str, str]) -> None:
    path = _sha_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(url, headers=_request_headers("application/vnd.github+json"))
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _download_raw(raw_url: str, dest: Path) -> None:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.netloc.lower() == "raw.githubusercontent.com":
        raw_url = f"{_API_BASE}/contents/{parsed.path.split(f'/{GITHUB_BRANCH}/', 1)[-1]}?ref={GITHUB_BRANCH}"
        request = urllib.request.Request(raw_url, headers=_request_headers("application/vnd.github.raw"))
    else:
        request = urllib.request.Request(raw_url, headers=_request_headers())
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=30) as response:
        dest.write_bytes(response.read())


def check_app_version() -> tuple[bool, str, str]:
    url = f"{_API_BASE}/releases/latest"
    try:
        payload = _fetch_json(url)
    except Exception:
        return False, "", ""

    if not isinstance(payload, dict):
        return False, "", ""

    latest_version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    release_url = str(payload.get("html_url") or "").strip()
    if not latest_version:
        return False, "", release_url
    return _is_newer_version(latest_version, APP_VERSION), latest_version, release_url


def sync_scripts() -> SyncResult:
    result = SyncResult(ok=False)
    try:
        manifest = _load_sha_manifest()
        new_manifest = dict(manifest)

        # Sync scripts.json
        scripts_json_api_url = f"{_API_BASE}/contents/resources/scripts.json?ref={GITHUB_BRANCH}"
        scripts_json_raw_url = f"{_RAW_BASE}/resources/scripts.json"
        try:
            meta = _fetch_json(scripts_json_api_url)
            remote_sha: str = meta["sha"]  # type: ignore[index]
            cached_scripts_json = scripts_json_cache_path()
            if remote_sha != manifest.get("scripts.json", "") or not cached_scripts_json.exists():
                _download_raw(scripts_json_raw_url, scripts_json_cache_path())
                is_new = "scripts.json" not in manifest
                new_manifest["scripts.json"] = remote_sha
                (result.new if is_new else result.updated).append("scripts.json")
        except Exception as exc:
            result.errors.append(f"scripts.json: {exc}")

        # Sync scripts directory
        dir_api_url = f"{_API_BASE}/contents/resources/scripts?ref={GITHUB_BRANCH}"
        try:
            entries = _fetch_json(dir_api_url)
            for entry in entries:  # type: ignore[union-attr]
                if entry.get("type") != "file":  # type: ignore[union-attr]
                    continue
                name: str = entry["name"]
                remote_sha = entry["sha"]
                raw_url: str = entry["download_url"]
                cached_script = scripts_cache_dir() / name
                if remote_sha != manifest.get(name, "") or not cached_script.exists():
                    try:
                        _download_raw(raw_url, cached_script)
                        is_new = name not in manifest
                        new_manifest[name] = remote_sha
                        (result.new if is_new else result.updated).append(name)
                    except Exception as exc:
                        result.errors.append(f"{name}: {exc}")
        except Exception as exc:
            result.errors.append(f"scripts dir: {exc}")

        try:
            update_available, latest_version, release_url = check_app_version()
            result.app_update_available = update_available
            result.latest_version = latest_version
            result.release_url = release_url
        except Exception as exc:
            result.version_error = str(exc)

        _save_sha_manifest(new_manifest)
        result.ok = not result.errors

    except Exception as exc:
        result.errors.append(str(exc))

    return result
