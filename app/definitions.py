from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(slots=True)
class AugmentDefinition:
    slot: str
    name: str
    image: str


@dataclass(slots=True)
class PerkDefinition:
    name: str
    image: str
    augments: list[AugmentDefinition]


@dataclass(slots=True)
class TimingDefinition:
    key: str
    label: str
    flag: str
    value: str
    suffix: str
    control: str
    false_value: str
    column: str


@dataclass(slots=True)
class KeybindDefinition:
    key: str
    label: str
    flag: str
    value: str
    placeholder: str


@dataclass(slots=True)
class ScriptDefinition:
    id: str
    name: str
    kind: str
    entry: str
    description: str
    args: list[str]
    setup: list[str]
    timings: list[TimingDefinition]
    keybinds: list[KeybindDefinition]
    accent: str


def _parse_perks(items: list[dict]) -> list[PerkDefinition]:
    perks: list[PerkDefinition] = []
    for perk in items:
        augments = [
            AugmentDefinition(
                slot=augment.get("slot", "Minor"),
                name=augment["name"],
                image=augment.get("image", ""),
            )
            for augment in perk.get("augments", [])
        ]
        perks.append(
            PerkDefinition(
                name=perk["name"],
                image=perk.get("image", ""),
                augments=augments,
            )
        )
    return perks


def _from_json_file(config_path: Path) -> list[ScriptDefinition]:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    items = raw.get("scripts", [])
    definitions: list[ScriptDefinition] = []

    for item in items:
        timings = [
            TimingDefinition(
                key=timing["key"],
                label=timing["label"],
                flag=timing["flag"],
                value=str(timing["value"]),
                suffix=timing.get("suffix", ""),
                control=timing.get("control", "number"),
                false_value=str(timing.get("false_value", "0")),
                column=timing.get("column", "left"),
            )
            for timing in item.get("timings", [])
        ]
        keybinds = [
            KeybindDefinition(
                key=keybind["key"],
                label=keybind["label"],
                flag=keybind["flag"],
                value=str(keybind["value"]),
                placeholder=keybind.get("placeholder", ""),
            )
            for keybind in item.get("keybinds", [])
        ]
        definitions.append(
            ScriptDefinition(
                id=item["id"],
                name=item["name"],
                kind=item["kind"],
                entry=item["entry"],
                description=item.get("description", "").strip(),
                args=item.get("args", []),
                setup=item.get("setup", []),
                timings=timings,
                keybinds=keybinds,
                accent=item.get("accent", "#8b5cf6"),
            )
        )

    return definitions


def _discover_ahk(project_root: Path) -> list[ScriptDefinition]:
    definitions: list[ScriptDefinition] = []

    for script_path in sorted(project_root.glob("*.ahk")):
        definitions.append(
            ScriptDefinition(
                id=f"ahk-{script_path.stem.lower().replace(' ', '-')}",
                name=script_path.stem,
                kind="ahk",
                entry=script_path.name,
                description="Discovered from project root.",
                args=[],
                setup=[],
                timings=[],
                keybinds=[],
                accent="#8b5cf6",
            )
        )

    scripts_dir = project_root / "resources" / "scripts"
    for script_path in sorted(scripts_dir.glob("*.ahk")):
        definitions.append(
            ScriptDefinition(
                id=f"script-{script_path.stem.lower().replace(' ', '-')}",
                name=script_path.stem,
                kind="ahk",
                entry=f"scripts/{script_path.name}",
                description="Discovered from resources/scripts.",
                args=[],
                setup=[],
                timings=[],
                keybinds=[],
                accent="#8b5cf6",
            )
        )

    imported_dir = project_root / "resources" / "imported"
    for script_path in sorted(imported_dir.glob("*.ahk")):
        definitions.append(
            ScriptDefinition(
                id=f"bundle-{script_path.stem.lower().replace(' ', '-')}",
                name=f"{script_path.stem} (Bundled)",
                kind="ahk",
                entry=f"imported/{script_path.name}",
                description="Bundled into build from project root AHK file.",
                args=[],
                setup=[],
                timings=[],
                keybinds=[],
                accent="#8b5cf6",
            )
        )

    return definitions


def load_definitions(config_path: Path, project_root: Path) -> list[ScriptDefinition]:
    definitions = _from_json_file(config_path)
    seen_entries = {item.entry for item in definitions}

    for item in _discover_ahk(project_root):
        if item.entry not in seen_entries:
            definitions.append(item)
            seen_entries.add(item.entry)

    return definitions


def load_shared_perks(config_path: Path) -> list[PerkDefinition]:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return _parse_perks(raw.get("perks", []))
