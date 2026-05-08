from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


GITHUB_REPO = "Lorenso0/Off-Limits-AFK"
GITHUB_BRANCH = "main"
_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"
_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "OffLimitsAFKLauncher",
}


@dataclass(slots=True)
class SyncResult:
    ok: bool
    updated: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

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


def _appdata_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / "OffLimits" / "AFK"


def scripts_cache_dir() -> Path:
    return _appdata_dir() / "scripts"


def scripts_json_cache_path() -> Path:
    return _appdata_dir() / "scripts.json"


def _sha_manifest_path() -> Path:
    return _appdata_dir() / "script_shas.json"


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
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _download_raw(raw_url: str, dest: Path) -> None:
    request = urllib.request.Request(raw_url, headers={"User-Agent": "OffLimitsAFKLauncher"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=30) as response:
        dest.write_bytes(response.read())


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
            if remote_sha != manifest.get("scripts.json", ""):
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
                if remote_sha != manifest.get(name, ""):
                    _download_raw(raw_url, scripts_cache_dir() / name)
                    is_new = name not in manifest
                    new_manifest[name] = remote_sha
                    (result.new if is_new else result.updated).append(name)
        except Exception as exc:
            result.errors.append(f"scripts dir: {exc}")

        _save_sha_manifest(new_manifest)
        result.ok = True

    except Exception as exc:
        result.errors.append(str(exc))

    return result
