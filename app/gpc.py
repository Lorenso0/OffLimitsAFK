from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .definitions import GpcActionStep, ScriptDefinition
from .runtime import managed_runtime_dir


ACTION_LABELS = {
    "fire": "Fire",
    "ads": "Aim Down Sights",
    "melee": "Melee",
    "lethal": "Lethal Equipment",
    "weapon_switch": "Weapon Switch",
    "scoreboard": "Scoreboard",
}


PLATFORM_LABELS = {
    "xbox": "Xbox",
    "playstation": "PlayStation",
}


BUTTON_CHOICES = {
    "xbox": [
        ("Right Trigger", "XB1_RT"),
        ("Left Trigger", "XB1_LT"),
        ("Right Bumper", "XB1_RB"),
        ("Left Bumper", "XB1_LB"),
        ("Y", "XB1_Y"),
        ("B", "XB1_B"),
        ("A", "XB1_A"),
        ("X", "XB1_X"),
        ("View", "XB1_VIEW"),
        ("Menu", "XB1_MENU"),
        ("D-Pad Up", "XB1_UP"),
        ("D-Pad Down", "XB1_DOWN"),
        ("D-Pad Left", "XB1_LEFT"),
        ("D-Pad Right", "XB1_RIGHT"),
        ("Left Stick Click", "XB1_LS"),
        ("Right Stick Click", "XB1_RS"),
    ],
    "playstation": [
        ("R2", "PS4_R2"),
        ("L2", "PS4_L2"),
        ("R1", "PS4_R1"),
        ("L1", "PS4_L1"),
        ("Triangle", "PS4_TRIANGLE"),
        ("Circle", "PS4_CIRCLE"),
        ("Cross", "PS4_CROSS"),
        ("Square", "PS4_SQUARE"),
        ("Share", "PS4_SHARE"),
        ("Options", "PS4_OPTIONS"),
        ("D-Pad Up", "PS4_UP"),
        ("D-Pad Down", "PS4_DOWN"),
        ("D-Pad Left", "PS4_LEFT"),
        ("D-Pad Right", "PS4_RIGHT"),
        ("L3", "PS4_L3"),
        ("R3", "PS4_R3"),
    ],
}


DEFAULT_ACTION_MAPS = {
    "xbox": {
        "fire": "XB1_RT",
        "ads": "XB1_LT",
        "melee": "XB1_B",
        "lethal": "XB1_RB",
        "weapon_switch": "XB1_Y",
        "scoreboard": "XB1_VIEW",
    },
    "playstation": {
        "fire": "PS4_R2",
        "ads": "PS4_L2",
        "melee": "PS4_CIRCLE",
        "lethal": "PS4_R1",
        "weapon_switch": "PS4_TRIANGLE",
        "scoreboard": "PS4_SHARE",
    },
}


@dataclass(frozen=True, slots=True)
class GpcToggleCombo:
    id: str
    label: str
    toggle_primary: dict[str, str]
    toggle_secondary: dict[str, str]
    stop_primary: dict[str, str]
    stop_secondary: dict[str, str]


TOGGLE_COMBOS = [
    GpcToggleCombo(
        id="view_share_up_down",
        label="View/Share + Up to toggle, View/Share + Down to stop",
        toggle_primary={"xbox": "XB1_VIEW", "playstation": "PS4_SHARE"},
        toggle_secondary={"xbox": "XB1_UP", "playstation": "PS4_UP"},
        stop_primary={"xbox": "XB1_VIEW", "playstation": "PS4_SHARE"},
        stop_secondary={"xbox": "XB1_DOWN", "playstation": "PS4_DOWN"},
    ),
    GpcToggleCombo(
        id="menu_options_left_right",
        label="Menu/Options + Left to toggle, Menu/Options + Right to stop",
        toggle_primary={"xbox": "XB1_MENU", "playstation": "PS4_OPTIONS"},
        toggle_secondary={"xbox": "XB1_LEFT", "playstation": "PS4_LEFT"},
        stop_primary={"xbox": "XB1_MENU", "playstation": "PS4_OPTIONS"},
        stop_secondary={"xbox": "XB1_RIGHT", "playstation": "PS4_RIGHT"},
    ),
    GpcToggleCombo(
        id="sticks_bumpers",
        label="L3 + R3 to toggle, LB/L1 + RB/R1 to stop",
        toggle_primary={"xbox": "XB1_LS", "playstation": "PS4_L3"},
        toggle_secondary={"xbox": "XB1_RS", "playstation": "PS4_R3"},
        stop_primary={"xbox": "XB1_LB", "playstation": "PS4_L1"},
        stop_secondary={"xbox": "XB1_RB", "playstation": "PS4_R1"},
    ),
]


def export_dir() -> Path:
    target = managed_runtime_dir() / "exports"
    target.mkdir(parents=True, exist_ok=True)
    return target


def default_export_path(definition: ScriptDefinition) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in definition.name).strip()
    safe_name = safe_name or "script"
    return export_dir() / f"{safe_name}.gpc"


def get_platform_choices() -> list[tuple[str, str]]:
    return [(label, key) for key, label in PLATFORM_LABELS.items()]


def get_button_choices(platform: str) -> list[tuple[str, str]]:
    if platform not in BUTTON_CHOICES:
        raise ValueError(f"Unsupported GPC platform: {platform}")
    return BUTTON_CHOICES[platform]


def get_default_action_map(platform: str) -> dict[str, str]:
    if platform not in DEFAULT_ACTION_MAPS:
        raise ValueError(f"Unsupported GPC platform: {platform}")
    return dict(DEFAULT_ACTION_MAPS[platform])


def get_toggle_combo_choices() -> list[tuple[str, str]]:
    return [(combo.label, combo.id) for combo in TOGGLE_COMBOS]


def get_export_required_actions(definition: ScriptDefinition) -> list[str]:
    gpc = definition.gpc
    if gpc is None:
        return []
    return [action for action in gpc.required_actions if action != "scoreboard"]


def build_gpc_script(
    definition: ScriptDefinition,
    option_overrides: dict[str, str] | None,
    platform: str,
    action_to_button: dict[str, str],
    toggle_combo_id: str,
) -> str:
    gpc = definition.gpc
    if gpc is None or not gpc.supported:
        raise ValueError(f"{definition.name} does not have GPC export metadata yet.")
    if gpc.target != "cronus_zen":
        raise ValueError(f"{definition.name} targets unsupported GPC device '{gpc.target}'.")

    if platform not in PLATFORM_LABELS:
        raise ValueError(f"Unsupported GPC platform: {platform}")

    values = _resolve_values(definition, option_overrides)
    if "scoreboard_toggling" in values:
        values["scoreboard_toggling"] = "0"

    required_actions = get_export_required_actions(definition)
    missing_actions = [action for action in required_actions if not action_to_button.get(action, "").strip()]
    if missing_actions:
        labels = ", ".join(ACTION_LABELS.get(action, action) for action in missing_actions)
        raise ValueError(f"Missing controller mapping for: {labels}.")

    toggle_combo = next((item for item in TOGGLE_COMBOS if item.id == toggle_combo_id), None)
    if toggle_combo is None:
        raise ValueError(f"Unknown toggle combo: {toggle_combo_id}")

    expanded_steps = _expand_steps(gpc.actions, values)
    if not expanded_steps:
        raise ValueError(f"{definition.name} has no exportable GPC steps.")

    timing_names, random_waits = _collect_timing_usage(expanded_steps)
    timing_symbols = {key: _symbolize(key) for key in timing_names}
    random_symbols = {f"random_wait_{index}": f"RANDOM_WAIT_{index}" for index in range(len(random_waits))}

    sequence = _render_steps(expanded_steps, action_to_button, timing_symbols, random_symbols)

    script_name = _symbolize(definition.name)
    platform_name = PLATFORM_LABELS[platform]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    action_lines = []
    for action in required_actions:
        button = action_to_button[action]
        action_lines.append(f"define {action.upper()}_BTN = {button};")

    toggle_lines = [
        f"define TOGGLE_PRIMARY = {toggle_combo.toggle_primary[platform]};",
        f"define TOGGLE_SECONDARY = {toggle_combo.toggle_secondary[platform]};",
        f"define STOP_PRIMARY = {toggle_combo.stop_primary[platform]};",
        f"define STOP_SECONDARY = {toggle_combo.stop_secondary[platform]};",
    ]

    config_lines = [f"int {timing_symbols[key]} = {_safe_int(values[key])};" for key in timing_names]
    for index, _item in enumerate(random_waits):
        config_lines.append(f"int {random_symbols[f'random_wait_{index}']} = 0;")
    config_lines.extend(
        [
            "int script_enabled = 0;",
            "int toggle_pressed = 0;",
            "int stop_pressed = 0;",
        ]
    )

    pre_run_lines: list[str] = []
    for index, item in enumerate(random_waits):
        base = timing_symbols[item.duration_timing]
        jitter = timing_symbols[item.random_timing]
        pre_run_lines.append(
            f"        {random_symbols[f'random_wait_{index}']} = {base} + random(0, {jitter});"
        )

    notes = "\n".join(f"// Note: {note}" for note in gpc.notes)
    if notes:
        notes += "\n"

    pre_run_block = "\n".join(pre_run_lines)
    if pre_run_block:
        pre_run_block += "\n"

    return (
        f"// Generated by Off Limits AFK on {generated_at}.\n"
        f"// Source script: {definition.name}\n"
        f"// Target platform preset: {platform_name}\n"
        f"// Toggle combo: {toggle_combo.label}\n"
        f"{notes}"
        "\n"
        + "\n".join(action_lines)
        + "\n"
        + "\n".join(toggle_lines)
        + "\n\n"
        + "\n".join(config_lines)
        + "\n\n"
        + "main {\n"
        + "    toggle_pressed = event_press(TOGGLE_SECONDARY) && get_val(TOGGLE_PRIMARY);\n"
        + "    stop_pressed = event_press(STOP_SECONDARY) && get_val(STOP_PRIMARY);\n\n"
        + "    if (stop_pressed) {\n"
        + "        script_enabled = 0;\n"
        + f"        combo_stop({script_name}_CYCLE);\n"
        + "    }\n\n"
        + "    if (toggle_pressed) {\n"
        + "        script_enabled = !script_enabled;\n"
        + "        if (!script_enabled) {\n"
        + f"            combo_stop({script_name}_CYCLE);\n"
        + "        }\n"
        + "    }\n\n"
        + f"    if (script_enabled && !combo_running({script_name}_CYCLE)) {{\n"
        + pre_run_block
        + f"        combo_run({script_name}_CYCLE);\n"
        + "    }\n"
        + "}\n\n"
        + f"combo {script_name}_CYCLE {{\n"
        + sequence
        + "\n}\n"
    )


def _resolve_values(definition: ScriptDefinition, option_overrides: dict[str, str] | None) -> dict[str, str]:
    resolved: dict[str, str] = {}
    option_overrides = option_overrides or {}
    for timing in definition.timings:
        resolved[timing.key] = str(option_overrides.get(timing.key, timing.value)).strip() or str(timing.value)
    for keybind in definition.keybinds:
        resolved[keybind.key] = str(option_overrides.get(keybind.key, keybind.value)).strip() or str(keybind.value)
    return resolved


def _expand_steps(steps: list[GpcActionStep], values: dict[str, str]) -> list[GpcActionStep]:
    expanded: list[GpcActionStep] = []
    for step in steps:
        if step.kind == "conditional":
            if not step.condition_timing:
                raise ValueError("Conditional GPC step is missing condition_timing.")
            if _is_enabled(values.get(step.condition_timing, "0")):
                expanded.extend(_expand_steps(step.steps, values))
            continue
        expanded.append(step)
    return expanded


def _collect_timing_usage(steps: list[GpcActionStep]) -> tuple[list[str], list[GpcActionStep]]:
    timing_names: list[str] = []
    random_waits: list[GpcActionStep] = []

    def add_timing(key: str) -> None:
        if key and key not in timing_names:
            timing_names.append(key)

    for step in steps:
        if step.kind not in {"press", "hold", "wait", "set", "release"}:
            raise ValueError(f"Unsupported GPC action kind: {step.kind}")
        add_timing(step.duration_timing)
        add_timing(step.random_timing)
        if step.kind == "wait" and step.random_timing:
            random_waits.append(step)

    return timing_names, random_waits


def _render_steps(
    steps: list[GpcActionStep],
    action_to_button: dict[str, str],
    timing_symbols: dict[str, str],
    random_symbols: dict[str, str],
) -> str:
    rendered: list[str] = []
    random_index = 0

    for step in steps:
        if step.kind == "set":
            button = _action_button(step.action, action_to_button)
            rendered.append(f"    set_val({button}, {step.value});")
            continue

        if step.kind == "release":
            button = _action_button(step.action, action_to_button)
            rendered.append(f"    set_val({button}, 0);")
            continue

        if step.kind in {"press", "hold"}:
            button = _action_button(step.action, action_to_button)
            duration = _duration_expr(step, timing_symbols)
            rendered.extend(
                [
                    f"    set_val({button}, {step.value});",
                    f"    wait({duration});",
                    f"    set_val({button}, 0);",
                ]
            )
            continue

        if step.kind == "wait":
            if step.random_timing:
                name = random_symbols[f"random_wait_{random_index}"]
                random_index += 1
                rendered.append(f"    wait({name});")
            else:
                rendered.append(f"    wait({_duration_expr(step, timing_symbols)});")
            continue

        raise ValueError(f"Unsupported GPC action kind: {step.kind}")

    return "\n".join(rendered)


def _duration_expr(step: GpcActionStep, timing_symbols: dict[str, str]) -> str:
    if step.duration_timing:
        return timing_symbols[step.duration_timing]
    if step.duration is not None:
        return str(step.duration)
    raise ValueError(f"GPC step '{step.kind}' is missing a duration.")


def _action_button(action: str, action_to_button: dict[str, str]) -> str:
    if not action:
        raise ValueError("GPC step is missing an action.")
    button = action_to_button.get(action, "").strip()
    if not button:
        raise ValueError(f"No controller mapping provided for action '{action}'.")
    return button


def _safe_int(value: str) -> int:
    try:
        return max(0, int(str(value).strip()))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid numeric timing value: {value}") from exc


def _is_enabled(value: str) -> bool:
    return str(value).strip().lower() not in {"", "0", "false", "off", "no"}


def _symbolize(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.upper())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "VALUE"
