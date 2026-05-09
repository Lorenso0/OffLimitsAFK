from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading

from PySide6.QtCore import QPoint, Qt, QSize, Signal
from PySide6.QtGui import QAction, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .definitions import (
    AugmentDefinition,
    KeybindDefinition,
    PerkDefinition,
    ScriptDefinition,
    TimingDefinition,
    load_definitions,
    load_shared_perks,
)
from .runtime import (
    active_scripts_json_path,
    current_ahk_runtime_label,
    format_keybind_display,
    keybind_settings_path,
    launch_script,
    normalize_keybind_value,
    project_root,
    resolve_entry,
    resources_root,
    stop_managed_ahk_scripts,
    stop_process,
)
from .updater import SyncResult, sync_scripts

# Design resolution height â€” all pixel constants are authored at this size.
_DESIGN_H = 1020
_SF: float = 1.0


def _s(n: int) -> int:
    """Scale a pixel value by the current screen scale factor."""
    return max(1, int(n * _SF))


class ThemedDialog(QDialog):
    def __init__(self, title: str, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colors = colors
        self.drag_origin: QPoint | None = None
        self.start_window_pos: QPoint | None = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_s(10), _s(10), _s(10), _s(10))
        outer.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("dialogShell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        outer.addWidget(self.shell)

        self.titlebar = QFrame()
        self.titlebar.setObjectName("dialogTitlebar")
        titlebar_layout = QHBoxLayout(self.titlebar)
        titlebar_layout.setContentsMargins(_s(16), _s(10), _s(10), _s(10))
        titlebar_layout.setSpacing(_s(10))
        shell_layout.addWidget(self.titlebar)

        accent = QFrame()
        accent.setObjectName("dialogAccent")
        accent.setFixedSize(_s(6), _s(22))
        titlebar_layout.addWidget(accent, 0, Qt.AlignVCenter)

        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        titlebar_layout.addWidget(title_label)

        titlebar_layout.addStretch(1)

        close_button = QPushButton("X")
        close_button.setObjectName("dialogCloseButton")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setFixedSize(_s(34), _s(26))
        close_button.clicked.connect(self.reject)
        titlebar_layout.addWidget(close_button)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(_s(18), _s(18), _s(18), _s(18))
        self.body_layout.setSpacing(_s(12))
        shell_layout.addWidget(self.body)

        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            #dialogShell {{
                background: {self.colors["panel"]};
                border: 1px solid #6b479d;
                border-radius: {_s(14)}px;
            }}
            #dialogTitlebar {{
                background: {self.colors["panel_alt"]};
                border-top-left-radius: {_s(14)}px;
                border-top-right-radius: {_s(14)}px;
                border-bottom: 1px solid #6b479d;
            }}
            #dialogAccent {{
                background: {self.colors["accent"]};
                border-radius: {_s(3)}px;
            }}
            #dialogTitle {{
                color: {self.colors["text"]};
                font: 700 {_s(17)}px "Segoe UI";
            }}
            #dialogCloseButton {{
                background: {self.colors["panel_alt"]};
                color: {self.colors["text"]};
                border: none;
                border-radius: {_s(8)}px;
                font: 700 {_s(13)}px "Segoe UI";
            }}
            #dialogCloseButton:hover {{
                background: {self.colors["danger_hover"]};
            }}
            #dialogCard {{
                background: {self.colors["card"]};
                border: 1px solid #312049;
                border-radius: {_s(12)}px;
            }}
            #dialogHint {{
                color: {self.colors["muted"]};
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #timingTitle {{
                color: {self.colors["text"]};
                font: 700 {_s(15)}px "Segoe UI";
            }}
            #timingLabel {{
                color: {self.colors["text"]};
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #timingInput {{
                background: {self.colors["panel_alt"]};
                color: {self.colors["text"]};
                border: 1px solid #312049;
                border-radius: {_s(8)}px;
                padding: {_s(8)}px {_s(10)}px;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #timingInput:focus {{
                border: 1px solid {self.colors["accent"]};
            }}
            #dialogGhostButton {{
                background: {self.colors["panel_alt"]};
                color: {self.colors["text"]};
                border: 1px solid #7148ad;
                border-radius: {_s(10)}px;
                padding: {_s(12)}px {_s(18)}px;
                font: 700 {_s(14)}px "Segoe UI";
            }}
            #dialogGhostButton:hover {{
                background: {self.colors["hover"]};
            }}
            #dialogSaveButton {{
                background: {self.colors["button"]};
                color: {self.colors["text"]};
                border: 1px solid {self.colors["accent"]};
                border-radius: {_s(10)}px;
                padding: {_s(12)}px {_s(18)}px;
                font: 700 {_s(14)}px "Segoe UI";
            }}
            #dialogSaveButton:hover {{
                background: {self.colors["button_hover"]};
            }}
            """
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self.titlebar.geometry().contains(event.position().toPoint()):
            self.drag_origin = event.globalPosition().toPoint()
            self.start_window_pos = self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.drag_origin is not None and self.start_window_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self.drag_origin
            self.move(self.start_window_pos + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self.drag_origin = None
        self.start_window_pos = None
        super().mouseReleaseEvent(event)


class OffLimitsWindow(QMainWindow):
    sync_completed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(_s(1360), _s(1020))
        self.setMinimumSize(_s(1260), _s(980))

        self.definitions: list[ScriptDefinition] = []
        self._reload_definitions()
        self.global_keybinds = self._build_global_keybinds()
        self.keybind_settings = self._load_keybind_settings()
        self._apply_saved_keybinds()
        self.keybinds_initialized = bool(self.keybind_settings)
        self.shared_perks = load_shared_perks(resources_root() / "loadout.json")
        self.selected: ScriptDefinition | None = None
        self.running_definition: ScriptDefinition | None = None
        self.running_process: subprocess.Popen[str] | None = None
        self.timing_inputs: dict[str, QWidget] = {}
        self.global_keybind_inputs: dict[str, QLineEdit] = {}
        self.drag_origin: QPoint | None = None
        self.start_window_pos: QPoint | None = None
        self.game_var = QLabel()
        self.colors = {
            "bg": "#05040a",
            "shell": "#090812",
            "panel": "#10101a",
            "panel_alt": "#0b0a14",
            "card": "#0a0912",
            "line": "#3a2857",
            "line_soft": "#261938",
            "text": "#f6f3ff",
            "muted": "#b7abd4",
            "accent": "#a855f7",
            "accent_2": "#7c3aed",
            "accent_soft": "#27153b",
            "button": "#7c3aed",
            "button_hover": "#8b5cf6",
            "hover": "#1a1328",
            "danger_hover": "#7f1d1d",
        }

        self.setObjectName("window")
        self.sync_completed.connect(self._on_sync_done)
        self._build_ui()
        self._apply_styles()
        self._populate_script_menu()
        self._refresh_keybind_summary()
        self._refresh_keybind_button_state()
        self._render_perks()
        self._clear_selection()
        self._start_sync()

    def _build_ui(self) -> None:
        outer = QWidget()
        outer.setObjectName("outer")
        self.setCentralWidget(outer)

        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(_s(10), _s(10), _s(10), _s(10))
        outer_layout.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("shell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        outer_layout.addWidget(self.shell)

        self._build_titlebar(shell_layout)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(_s(16), _s(14), _s(16), _s(14))
        body_layout.setSpacing(_s(14))
        shell_layout.addWidget(body)

        top_row = QHBoxLayout()
        top_row.setSpacing(_s(12))
        top_row.setAlignment(Qt.AlignTop)
        body_layout.addLayout(top_row)

        self.selector_panel = self._build_selector_panel()
        self.selector_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        top_row.addWidget(self.selector_panel, 1)

        self.requirements_panel = self._build_requirements_panel()
        self.requirements_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        top_row.addWidget(self.requirements_panel, 1)

        self.perks_panel = self._build_perks_panel()
        body_layout.addWidget(self.perks_panel)

        self.footer = self._build_footer()
        body_layout.addWidget(self.footer)

    def _build_titlebar(self, parent_layout: QVBoxLayout) -> None:
        self.titlebar = QFrame()
        self.titlebar.setObjectName("titlebar")
        layout = QHBoxLayout(self.titlebar)
        layout.setContentsMargins(_s(18), _s(10), _s(10), _s(10))
        layout.setSpacing(0)
        parent_layout.addWidget(self.titlebar)

        title_left = QHBoxLayout()
        title_left.setSpacing(_s(14))
        layout.addLayout(title_left)

        logo = QLabel()
        logo.setObjectName("logoLabel")
        logo.setPixmap(self._load_pixmap("pictures/logo.png", _s(24), _s(24)))
        logo.setFixedSize(_s(28), _s(28))
        logo.setAlignment(Qt.AlignCenter)
        title_left.addWidget(logo)

        afk = QLabel("[AFK]")
        afk.setObjectName("afkLabel")
        title_left.addWidget(afk)

        brand = QLabel("Off Limits AFK Scripts")
        brand.setObjectName("brandLabel")
        title_left.addWidget(brand)

        divider = QLabel("|")
        divider.setObjectName("dividerLabel")
        title_left.addWidget(divider)

        subtitle = QLabel("AFK scripts for Call of Duty")
        subtitle.setObjectName("subtitleLabel")
        title_left.addWidget(subtitle)

        title_left.addStretch(1)

        self.runtime_badge = QLabel(current_ahk_runtime_label())
        self.runtime_badge.setObjectName("runtimeBadge")
        layout.addWidget(self.runtime_badge, 0, Qt.AlignRight)

        controls = QHBoxLayout()
        controls.setSpacing(_s(6))
        layout.addLayout(controls)

        self.min_button = self._title_button("_")
        self.min_button.clicked.connect(self.showMinimized)
        controls.addWidget(self.min_button)

        self.max_button = self._title_button("[]")
        self.max_button.clicked.connect(self._toggle_maximize)
        controls.addWidget(self.max_button)

        self.close_button = self._title_button("X", danger=True)
        self.close_button.clicked.connect(self.close)
        controls.addWidget(self.close_button)

    def _title_button(self, text: str, danger: bool = False, width: int = 40) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(_s(width), _s(28))
        base = self.colors["panel_alt"]
        hover = self.colors["danger_hover"] if danger else self.colors["hover"]
        button.setStyleSheet(
            f"""
            QPushButton {{
                background: {base};
                color: {self.colors["text"]};
                border: none;
                border-radius: {_s(8)}px;
                font: 700 {_s(13)}px "Segoe UI";
            }}
            QPushButton:hover {{
                background: {hover};
            }}
            """
        )
        return button

    def _build_selector_panel(self) -> QWidget:
        panel = self._panel()
        layout = panel.layout()

        header = self._section_header("Script Selector", "</>")
        layout.addWidget(header)

        inner = self._inner_card()
        inner_layout = inner.layout()
        layout.addWidget(inner, 0, Qt.AlignTop)

        self.game_button = QPushButton("Black Ops 7 Zombies")
        self.game_button.setObjectName("selectorButton")
        self.game_button.clicked.connect(self._open_script_menu)
        inner_layout.addWidget(self.game_button)

        self.launch_button = QPushButton("Launch Selected Script")
        self.launch_button.setObjectName("launchButton")
        self.launch_button.clicked.connect(self._launch_selected)
        inner_layout.addWidget(self.launch_button)

        selected_bar = QFrame()
        selected_bar.setObjectName("selectedBar")
        selected_layout = QHBoxLayout(selected_bar)
        selected_layout.setContentsMargins(_s(14), _s(10), _s(14), _s(10))
        selected_layout.setSpacing(_s(12))
        inner_layout.addWidget(selected_bar)

        badge = QLabel("[*]")
        badge.setObjectName("selectedBadge")
        badge.setFixedWidth(_s(42))
        badge.setAlignment(Qt.AlignCenter)
        selected_layout.addWidget(badge)

        self.selected_script_label = QLabel("Selected Script: None")
        self.selected_script_label.setObjectName("selectedScriptLabel")
        selected_layout.addWidget(self.selected_script_label, 1)

        self.edit_keybinds_button = QPushButton("Edit Keybinds")
        self.edit_keybinds_button.setObjectName("inlineKeybindButton")
        self.edit_keybinds_button.setCursor(Qt.PointingHandCursor)
        self.edit_keybinds_button.setFlat(True)
        self.edit_keybinds_button.clicked.connect(self._open_keybind_dialog)
        selected_layout.addWidget(self.edit_keybinds_button, 0, Qt.AlignRight)

        self.selector_variables_card = QFrame()
        self.selector_variables_card.setObjectName("innerCard")
        self.selector_variables_card.setMinimumHeight(_s(168))
        self.selector_variables_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        selector_vars_layout = QVBoxLayout(self.selector_variables_card)
        selector_vars_layout.setContentsMargins(_s(12), _s(12), _s(12), _s(12))
        selector_vars_layout.setSpacing(_s(8))
        inner_layout.addWidget(self.selector_variables_card)

        selector_vars_title = QLabel("Script Variables")
        selector_vars_title.setObjectName("timingTitle")
        selector_vars_layout.addWidget(selector_vars_title)

        self.selector_variables_empty = QLabel("Select a script to edit its variables.")
        self.selector_variables_empty.setObjectName("requirementsDesc")
        self.selector_variables_empty.setWordWrap(True)
        selector_vars_layout.addWidget(self.selector_variables_empty)

        self.timing_container = QWidget()
        self.timing_layout = QVBoxLayout(self.timing_container)
        self.timing_layout.setContentsMargins(0, 0, 0, 0)
        self.timing_layout.setSpacing(_s(8))
        self.timing_layout.setAlignment(Qt.AlignTop)
        selector_vars_layout.addWidget(self.timing_container)

        layout.addStretch(1)
        return panel

    def _build_requirements_panel(self) -> QWidget:
        panel = self._panel()
        layout = panel.layout()

        header = self._section_header("Requirements / Setup", ":::")
        layout.addWidget(header)

        self.requirements_inner = self._inner_card()
        inner_layout = self.requirements_inner.layout()
        layout.addWidget(self.requirements_inner)

        top = QHBoxLayout()
        top.setSpacing(_s(14))
        inner_layout.addLayout(top)

        placeholder = QFrame()
        placeholder.setObjectName("previewBox")
        placeholder.setFixedSize(_s(78), _s(78))
        preview_layout = QVBoxLayout(placeholder)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(_s(6))
        preview_layout.setAlignment(Qt.AlignCenter)
        preview_icon = QLabel("IMG")
        preview_icon.setObjectName("previewText")
        preview_layout.addWidget(preview_icon, 0, Qt.AlignCenter)
        top.addWidget(placeholder, 0, Qt.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(_s(6))
        top.addLayout(title_col, 1)

        global_title = QLabel("Setup Requirements")
        global_title.setObjectName("requirementsTitle")
        title_col.addWidget(global_title)

        global_meta = QLabel("Required setup shown for every script")
        global_meta.setObjectName("requirementsMeta")
        title_col.addWidget(global_meta)

        global_desc = QLabel(
            "Follow these steps before selecting and launching any script."
        )
        global_desc.setObjectName("requirementsDesc")
        global_desc.setWordWrap(True)
        inner_layout.addWidget(global_desc)

        divider = QFrame()
        divider.setObjectName("dividerLine")
        divider.setFixedHeight(1)
        inner_layout.addWidget(divider)

        self.setup_container = QWidget()
        self.setup_layout = QVBoxLayout(self.setup_container)
        self.setup_layout.setContentsMargins(0, 0, 0, 0)
        self.setup_layout.setSpacing(_s(6))
        inner_layout.addWidget(self.setup_container)

        return panel

    def _build_perks_panel(self) -> QWidget:
        panel = self._panel()
        layout = panel.layout()

        header = self._section_header("Required Perks & Augments", "", right_small=True)
        layout.addWidget(header)

        self.perk_row = QWidget()
        self.perk_row_layout = QHBoxLayout(self.perk_row)
        self.perk_row_layout.setContentsMargins(0, 0, 0, 0)
        self.perk_row_layout.setSpacing(_s(12))
        layout.addWidget(self.perk_row)

        return panel

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(_s(18), _s(12), _s(18), _s(12))
        layout.setSpacing(_s(10))

        dot = QLabel("*")
        dot.setObjectName("statusDot")
        layout.addWidget(dot)

        self.status_label = QLabel("Status: Idle")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label, 1)

        self.sync_button = QPushButton("Sync")
        self.sync_button.setObjectName("syncButton")
        self.sync_button.setCursor(Qt.PointingHandCursor)
        self.sync_button.setToolTip("Re-download scripts from GitHub")
        self.sync_button.clicked.connect(self._start_sync)
        layout.addWidget(self.sync_button, 0, Qt.AlignRight)
        return footer

    def _panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(_s(18), _s(18), _s(18), _s(18))
        layout.setSpacing(_s(16))
        layout.setAlignment(Qt.AlignTop)
        return panel

    def _inner_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("innerCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(_s(14), _s(14), _s(14), _s(14))
        layout.setSpacing(_s(12))
        layout.setAlignment(Qt.AlignTop)
        return card

    def _section_header(self, title: str, right: str, right_small: bool = False) -> QWidget:
        frame = QWidget()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left = QHBoxLayout()
        left.setSpacing(_s(12))
        layout.addLayout(left)

        accent = QFrame()
        accent.setObjectName("sectionAccent")
        accent.setFixedSize(_s(6), _s(28))
        left.addWidget(accent)

        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        left.addWidget(title_label)

        layout.addStretch(1)

        right_label = QLabel(right)
        right_label.setObjectName("sectionRightSmall" if right_small else "sectionRight")
        layout.addWidget(right_label)
        return frame

    def _render_perks(self) -> None:
        while self.perk_row_layout.count():
            item = self.perk_row_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for perk in self.shared_perks:
            self.perk_row_layout.addWidget(self._build_perk_card(perk))
        self.perk_row_layout.addStretch(1)

    def _build_perk_card(self, perk: PerkDefinition) -> QWidget:
        card = QFrame()
        card.setObjectName("perkCard")
        card.setFixedSize(_s(296), _s(278))

        layout = QVBoxLayout(card)
        layout.setContentsMargins(_s(14), _s(14), _s(14), _s(14))
        layout.setSpacing(_s(10))

        head = QHBoxLayout()
        head.setSpacing(_s(12))
        layout.addLayout(head)

        icon = QLabel()
        icon.setPixmap(self._load_pixmap(perk.image, _s(48), _s(48)))
        icon.setFixedSize(_s(48), _s(48))
        icon.setAlignment(Qt.AlignCenter)
        head.addWidget(icon, 0, Qt.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(_s(4))
        head.addLayout(title_col, 1)

        perk_title = QLabel(perk.name)
        perk_title.setObjectName("perkTitle")
        title_col.addWidget(perk_title)

        summary = QLabel(self._augment_summary(perk))
        summary.setObjectName("perkSummary")
        title_col.addWidget(summary)

        for augment in perk.augments:
            layout.addWidget(self._build_augment_row(augment))

        layout.addStretch(1)
        return card

    def _build_augment_row(self, augment: AugmentDefinition) -> QWidget:
        row = QFrame()
        row.setObjectName("augmentRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(_s(10), _s(8), _s(10), _s(8))
        layout.setSpacing(_s(10))

        slot = QLabel(augment.slot.upper())
        slot.setObjectName("augmentSlot")
        slot.setFixedWidth(_s(54))
        layout.addWidget(slot)

        icon = QLabel()
        icon.setPixmap(self._load_pixmap(augment.image, _s(22), _s(22)))
        icon.setFixedSize(_s(22), _s(22))
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        name = QLabel(augment.name)
        name.setObjectName("augmentName")
        layout.addWidget(name, 1)

        return row

    def _build_timing_row(self, timing: TimingDefinition) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_s(8))

        if timing.control == "checkbox":
            checkbox = QCheckBox(timing.label)
            checkbox.setObjectName("timingCheckbox")
            checkbox.setChecked(timing.value.lower() in {"1", "true", "yes", "on"})
            checkbox.setMinimumWidth(_s(170))
            layout.addStretch(1)
            layout.addWidget(checkbox, 0, Qt.AlignHCenter)
            layout.addStretch(1)
            self.timing_inputs[timing.key] = checkbox
            return row

        label = QLabel(timing.label)
        label.setObjectName("timingLabel")
        label.setMinimumWidth(_s(138))
        layout.addWidget(label)

        entry = QLineEdit()
        entry.setObjectName("timingInput")
        entry.setText(timing.value)
        entry.setFixedWidth(_s(82))
        layout.addWidget(entry)
        self.timing_inputs[timing.key] = entry

        if timing.suffix:
            suffix = QLabel(timing.suffix)
            suffix.setObjectName("timingSuffix")
            layout.addWidget(suffix)

        layout.addStretch(1)
        return row

    def _populate_script_menu(self) -> None:
        self.script_menu = None

    def _definition_available(self, definition: ScriptDefinition) -> bool:
        return resolve_entry(definition.entry).exists()

    def _reload_definitions(self) -> None:
        definitions = load_definitions(
            active_scripts_json_path(),
            project_root(),
        )
        self.definitions = [definition for definition in definitions if self._definition_available(definition)]

    def _load_keybind_settings(self) -> dict[str, str]:
        path = keybind_settings_path()
        if not path.exists():
            return {}

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        settings: dict[str, str] = {}
        for key, value in raw.items():
            if isinstance(key, str) and value is not None and not isinstance(value, dict):
                settings[key] = normalize_keybind_value(str(value))

        for script_values in raw.values():
            if not isinstance(script_values, dict):
                continue
            for key, value in script_values.items():
                if isinstance(key, str) and value is not None and key not in settings:
                    settings[key] = normalize_keybind_value(str(value))
        return settings

    def _save_keybind_settings(self) -> None:
        path = keybind_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.keybind_settings, indent=2, sort_keys=True)
        path.write_text(payload + "\n", encoding="utf-8")

    def _build_global_keybinds(self) -> list[KeybindDefinition]:
        desired_order = [
            "toggle_key",
            "exit_key",
            "lethal_key",
            "weapon_switch_key",
            "scoreboard_key",
            "melee_key",
        ]
        found: dict[str, KeybindDefinition] = {}
        for definition in self.definitions:
            for keybind in definition.keybinds:
                found.setdefault(
                    keybind.key,
                    KeybindDefinition(
                        key=keybind.key,
                        label=keybind.label,
                        flag=keybind.flag,
                        value=keybind.value,
                        placeholder=keybind.placeholder,
                    ),
                )

        ordered: list[KeybindDefinition] = []
        for key in desired_order:
            if key in found:
                ordered.append(found[key])
        for key, keybind in found.items():
            if key not in desired_order:
                ordered.append(keybind)
        return ordered

    def _apply_saved_keybinds(self) -> None:
        global_values = {item.key: item for item in self.global_keybinds}
        for key, value in self.keybind_settings.items():
            if key in global_values:
                global_values[key].value = value
        for definition in self.definitions:
            for keybind in definition.keybinds:
                if keybind.key in global_values:
                    keybind.value = global_values[keybind.key].value

    def _persist_global_keybind_value(self, keybind: KeybindDefinition, value: str) -> None:
        resolved = normalize_keybind_value(value.strip() or keybind.placeholder or keybind.value)
        keybind.value = resolved
        self.keybind_settings[keybind.key] = resolved
        for definition in self.definitions:
            for item in definition.keybinds:
                if item.key == keybind.key:
                    item.value = resolved
        self._save_keybind_settings()
        self.keybinds_initialized = True
        self._refresh_keybind_summary()
        self._refresh_keybind_button_state()

    def _refresh_keybind_summary(self) -> None:
        return

    def _refresh_keybind_button_state(self) -> None:
        if self.keybinds_initialized:
            self.edit_keybinds_button.setProperty("attention", False)
            self.edit_keybinds_button.setToolTip("Open global keybind settings.")
        else:
            self.edit_keybinds_button.setProperty("attention", True)
            self.edit_keybinds_button.setToolTip("Set your keybinds before launching a script.")
        self.edit_keybinds_button.style().unpolish(self.edit_keybinds_button)
        self.edit_keybinds_button.style().polish(self.edit_keybinds_button)

    def _open_keybind_dialog(self) -> None:
        dialog = ThemedDialog("Global Keybinds", self.colors, self)
        dialog.resize(_s(420), _s(380))

        card = QFrame()
        card.setObjectName("dialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(_s(14), _s(14), _s(14), _s(14))
        card_layout.setSpacing(_s(10))
        dialog.body_layout.addWidget(card)

        title = QLabel("Global Keybinds")
        title.setObjectName("timingTitle")
        card_layout.addWidget(title)

        hint = QLabel("These keybinds apply everywhere they are used.")
        hint.setObjectName("dialogHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        self.global_keybind_inputs = {}
        for keybind in self.global_keybinds:
            row = QWidget(dialog)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(_s(8))

            label = QLabel(keybind.label)
            label.setObjectName("timingLabel")
            label.setMinimumWidth(_s(150))
            row_layout.addWidget(label)

            entry = QLineEdit()
            entry.setObjectName("timingInput")
            entry.setText(format_keybind_display(keybind.value))
            if keybind.placeholder:
                entry.setPlaceholderText(format_keybind_display(keybind.placeholder))
            entry.textEdited.connect(lambda _text, control=entry: self._force_uppercase_display(control))
            row_layout.addWidget(entry)
            self.global_keybind_inputs[keybind.key] = entry

            card_layout.addWidget(row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("dialogGhostButton")
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(cancel)

        save = QPushButton("Save")
        save.setObjectName("dialogSaveButton")
        save.clicked.connect(lambda: self._save_global_keybind_dialog(dialog))
        buttons.addWidget(save)

        dialog.body_layout.addLayout(buttons)
        dialog.exec()

    def _save_global_keybind_dialog(self, dialog: QDialog) -> None:
        for keybind in self.global_keybinds:
            control = self.global_keybind_inputs.get(keybind.key)
            if control is None:
                continue
            value = control.text().strip() or keybind.placeholder or keybind.value
            control.setText(value)
            self._persist_global_keybind_value(keybind, value)
        dialog.accept()

    def _force_uppercase_display(self, control: QLineEdit) -> None:
        text = control.text()
        upper = text.upper()
        if text == upper:
            return
        cursor = control.cursorPosition()
        control.blockSignals(True)
        control.setText(upper)
        control.setCursorPosition(cursor)
        control.blockSignals(False)

    def _open_script_menu(self) -> None:
        if self.script_menu is not None and self.script_menu.isVisible():
            self.script_menu.close()
            return

        if not self.definitions:
            self._clear_selection()
            self.status_label.setText("Status: No downloaded scripts available. Sync or restart after download.")
            QMessageBox.information(
                self,
                "No scripts available",
                "No downloaded scripts were found yet. Use Sync or restart after the download finishes.",
            )
            return

        menu = QMenu(self)
        menu.setObjectName("scriptMenu")
        menu.setMinimumWidth(self.game_button.width())
        for definition in self.definitions:
            action = QAction(definition.name, self)
            action.triggered.connect(lambda checked=False, item=definition: self._show_definition(item))
            menu.addAction(action)

        self.script_menu = menu
        self.status_label.setText("Status: Pick script from Black Ops 7 Zombies menu")
        menu.exec(self.game_button.mapToGlobal(self.game_button.rect().bottomLeft() + QPoint(0, 8)))
        if self.selected is None:
            self.status_label.setText("Status: Idle")

    def _clear_selection(self) -> None:
        self.selected = None
        self.game_button.setText("Black Ops 7 Zombies")
        self.selected_script_label.setText("Selected Script: None")
        self.status_label.setText("Status: Idle")
        self._refresh_setup(None)
        self._refresh_timings(None)
        self._refresh_launch_state()

    def _show_definition(self, definition: ScriptDefinition) -> None:
        if self._has_running_script() and self.running_definition is not None and self.running_definition.id != definition.id:
            result = self._stop_running_script()
            if not result.ok:
                self.status_label.setText(f"Status: {result.message}")
                QMessageBox.critical(self, "Stop failed", result.message)
                self._refresh_launch_state()
                return
        elif self.running_definition is not None and self.running_definition.id != definition.id:
            stop_managed_ahk_scripts(self.definitions)
            self.running_process = None
            self.running_definition = None

        self.selected = definition
        self.game_button.setText(definition.name)
        self.selected_script_label.setText(f"Selected Script: {definition.name}")
        if self._is_selected_running():
            self.status_label.setText(f"Status: Running {definition.name}")
        else:
            self.status_label.setText(f"Status: Ready to launch {definition.name}")
        self._refresh_setup(definition)
        self._refresh_timings(definition)
        self._refresh_launch_state()

    def _refresh_launch_state(self) -> None:
        if self._is_selected_running():
            self.launch_button.setText("End Script")
            self.launch_button.setStyleSheet(self._launch_button_style(active=True))
        elif self._has_running_script():
            self.launch_button.setText("Launch Selected Script")
            self.launch_button.setStyleSheet(self._launch_button_style(active=False))
        elif self.selected is None:
            self.launch_button.setText("Launch Selected Script")
            self.launch_button.setStyleSheet(self._launch_button_style(active=False))
        else:
            self.launch_button.setText("Launch Selected Script")
            self.launch_button.setStyleSheet(self._launch_button_style(active=True))

    def _refresh_setup(self, definition: ScriptDefinition | None) -> None:
        while self.setup_layout.count():
            item = self.setup_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        items = [
            "Load into Ashes of the Damned Directed mode and go up to Round Cap 7/10/12.",
            "Stand in the pictured spot and aim at the wooden post.",
            'Select your desired script, launch it and use the "Toggle Script" keybind to launch.',
        ]

        for item in items:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(_s(10))

            bullet = QLabel("*")
            bullet.setObjectName("setupBullet")
            layout.addWidget(bullet, 0, Qt.AlignTop)

            text = QLabel(item)
            text.setObjectName("setupItem")
            text.setWordWrap(True)
            layout.addWidget(text, 1)
            self.setup_layout.addWidget(row)

    def _refresh_timings(self, definition: ScriptDefinition | None) -> None:
        while self.timing_layout.count():
            item = self.timing_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.timing_inputs = {}

        if definition is None or not definition.timings:
            self.selector_variables_empty.show()
            return

        self.selector_variables_empty.hide()
        split = QWidget()
        split_layout = QHBoxLayout(split)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(_s(18))

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(_s(10))
        split_layout.addLayout(left_col, 1)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(_s(10))
        split_layout.addLayout(right_col, 0)

        right_rows: list[tuple[QWidget, bool]] = []  # (widget, is_checkbox)
        for timing in definition.timings:
            row = self._build_timing_row(timing)
            if timing.control == "checkbox":
                right_rows.append((row, True))
            elif timing.column == "right":
                right_rows.append((row, False))
            else:
                left_col.addWidget(row)

        # Add right-column items: regular ones first (top), then checkboxes
        for row, is_checkbox in sorted(right_rows, key=lambda x: x[1]):
            if is_checkbox:
                right_col.addWidget(row, 0, Qt.AlignCenter)
            else:
                right_col.addWidget(row)

        left_col.addStretch(1)
        if right_rows:
            right_col.addStretch(1)
        else:
            split_layout.addStretch(1)

        self.timing_layout.addWidget(split)

    def _launch_selected(self) -> None:
        if self.selected is None:
            QMessageBox.warning(self, "No script", "Pick script first.")
            return

        if self._is_selected_running():
            result = self._stop_running_script()
            if result.ok:
                self.status_label.setText(f"Status: Stopped {self.selected.name}")
            else:
                self.status_label.setText(f"Status: {result.message}")
                QMessageBox.critical(self, "Stop failed", result.message)
            self._refresh_launch_state()
            return

        if self._has_running_script():
            result = self._stop_running_script()
            if not result.ok:
                self.status_label.setText(f"Status: {result.message}")
                QMessageBox.critical(self, "Stop failed", result.message)
                self._refresh_launch_state()
                return

        stop_managed_ahk_scripts(self.definitions)
        self.running_process = None
        self.running_definition = None

        if not self.keybinds_initialized:
            self.status_label.setText("Status: Click Edit Keybinds and save your keybinds before launch")
            QMessageBox.information(
                self,
                "Set keybinds first",
                "Click Edit Keybinds first and save your keybinds so the script uses the correct controls.",
            )
            self._refresh_keybind_button_state()
            return

        option_overrides: dict[str, str] = {}
        if self.selected is not None:
            timing_map = {timing.key: timing for timing in self.selected.timings}
            for key, control in self.timing_inputs.items():
                timing = timing_map[key]
                if isinstance(control, QLineEdit):
                    option_overrides[key] = control.text().strip()
                elif isinstance(control, QCheckBox):
                    option_overrides[key] = timing.value if control.isChecked() else timing.false_value
            for keybind in self.selected.keybinds:
                option_overrides[keybind.key] = keybind.value
        result = launch_script(self.selected, option_overrides)
        self.status_label.setText(f"Status: {result.message}")
        if result.ok:
            self.running_process = result.process
            self.running_definition = self.selected
            self.status_label.setText(f"Status: Running {self.selected.name}")
            self._refresh_launch_state()
        else:
            QMessageBox.critical(self, "Launch failed", result.message)

    def _has_running_script(self) -> bool:
        if self.running_process is None:
            return False
        if self.running_process.poll() is None:
            return True
        self.running_process = None
        self.running_definition = None
        return False

    def _is_selected_running(self) -> bool:
        return (
            self.selected is not None
            and self.running_definition is not None
            and self.selected.id == self.running_definition.id
            and self._has_running_script()
        )

    def _stop_running_script(self):
        result = stop_process(self.running_process)
        if result.ok:
            self.running_process = None
            self.running_definition = None
        return result

    def _augment_summary(self, perk: PerkDefinition) -> str:
        major = sum(1 for augment in perk.augments if augment.slot.lower() == "major")
        minor = sum(1 for augment in perk.augments if augment.slot.lower() == "minor")
        parts: list[str] = []
        if major:
            parts.append(f"{major} Major" if major == 1 else f"{major} Majors")
        if minor:
            parts.append(f"{minor} Minor" if minor == 1 else f"{minor} Minors")
        return " + ".join(parts) if parts else "No augments listed"

    def _load_pixmap(self, relative_path: str, width: int, height: int) -> QPixmap:
        if not relative_path:
            return QPixmap()
        path = resources_root() / relative_path
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QPixmap()
        return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _launch_button_style(self, active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: #7c3aed;
                    color: #f6f3ff;
                    border: 1px solid #a855f7;
                    border-radius: {_s(10)}px;
                    padding: {_s(16)}px;
                    font: 700 {_s(18)}px "Segoe UI";
                }}
                QPushButton:hover {{
                    background: #8b5cf6;
                }}
            """
        return f"""
                QPushButton {{
                    background: #0b0a14;
                    color: #f6f3ff;
                    border: 1px solid #312049;
                    border-radius: {_s(10)}px;
                    padding: {_s(16)}px;
                    font: 700 {_s(18)}px "Segoe UI";
                }}
                QPushButton:hover {{
                    background: #1a1328;
                }}
            """

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            #shell {{
                background: #090812;
                border: 1px solid #6b479d;
                border-radius: {_s(14)}px;
            }}
            #titlebar {{
                background: #0b0a14;
                border-top-left-radius: {_s(14)}px;
                border-top-right-radius: {_s(14)}px;
                border-bottom: 1px solid #6b479d;
            }}
            #afkLabel {{
                color: #a855f7;
                font: 700 {_s(18)}px "Segoe UI";
            }}
            #brandLabel {{
                color: #f6f3ff;
                font: 700 {_s(20)}px "Segoe UI";
            }}
            #dividerLabel {{
                color: #7b6aa0;
                font: 400 {_s(16)}px "Segoe UI";
            }}
            #subtitleLabel {{
                color: #b7abd4;
                font: 400 {_s(14)}px "Segoe UI";
            }}
            #runtimeBadge {{
                background: #120d1d;
                color: #cdb8f4;
                border: 1px solid #4d3275;
                border-radius: {_s(10)}px;
                padding: {_s(6)}px {_s(12)}px;
                margin-right: {_s(10)}px;
                font: 700 {_s(12)}px "Segoe UI";
            }}
            #panel {{
                background: #10101a;
                border: 1px solid #312049;
                border-radius: {_s(12)}px;
            }}
            #innerCard {{
                background: #0a0912;
                border: 1px solid #312049;
                border-radius: {_s(12)}px;
            }}
            #sectionAccent {{
                background: #a855f7;
                border-radius: {_s(3)}px;
            }}
            #sectionTitle {{
                color: #f6f3ff;
                font: 700 {_s(18)}px "Segoe UI";
            }}
            #sectionRight {{
                color: #a855f7;
                font: 700 {_s(19)}px "Segoe UI Symbol";
            }}
            #sectionRightSmall {{
                color: #b7abd4;
                font: italic {_s(13)}px "Segoe UI";
            }}
            #selectorButton {{
                background: #0b0a14;
                color: #f6f3ff;
                border: 1px solid #7148ad;
                border-radius: {_s(10)}px;
                padding: {_s(16)}px {_s(18)}px;
                text-align: left;
                font: 400 {_s(16)}px "Segoe UI";
            }}
            #selectorButton:hover {{
                background: #1a1328;
            }}
            #selectedBar {{
                background: #0b0a14;
                border: 1px solid #312049;
                border-radius: {_s(10)}px;
            }}
            #selectedBadge {{
                background: #27153b;
                color: #a855f7;
                border: 1px solid #261938;
                border-radius: {_s(8)}px;
                font: 700 {_s(13)}px "Segoe UI";
            }}
            #selectedScriptLabel {{
                color: #f6f3ff;
                font: 400 {_s(15)}px "Segoe UI";
            }}
            #inlineKeybindButton {{
                background: transparent;
                color: #b7abd4;
                border: none;
                padding: 2px 0px;
                font: 600 {_s(12)}px "Segoe UI";
                text-align: right;
            }}
            #inlineKeybindButton:hover {{
                color: #f6f3ff;
                text-decoration: underline;
            }}
            #inlineKeybindButton[attention="true"] {{
                color: #f6f3ff;
                border-bottom: 1px solid #a855f7;
            }}
            #inlineKeybindButton[attention="true"]:hover {{
                color: #ffffff;
                text-decoration: underline;
            }}
            #infoIcon {{
                background: #0b0a14;
                color: #a855f7;
                border: 1px solid #7148ad;
                border-radius: {_s(15)}px;
                font: 700 {_s(17)}px "Consolas";
            }}
            #previewBox {{
                background: #120d1d;
                border: 1px solid #5a3d86;
                border-radius: {_s(12)}px;
            }}
            #previewText {{
                color: #a855f7;
                font: 700 {_s(16)}px "Segoe UI";
            }}
            #requirementsTitle {{
                color: #f6f3ff;
                font: 700 {_s(18)}px "Segoe UI";
            }}
            #requirementsMeta {{
                color: #b7abd4;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #requirementsDesc {{
                color: #b7abd4;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #dividerLine {{
                background: #312049;
            }}
            #setupBullet {{
                color: #a855f7;
                font: 700 {_s(14)}px "Segoe UI";
            }}
            #setupItem {{
                color: #f6f3ff;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #timingTitle {{
                color: #f6f3ff;
                font: 700 {_s(15)}px "Segoe UI";
            }}
            #timingLabel {{
                color: #f6f3ff;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #timingCheckbox {{
                color: #f6f3ff;
                spacing: {_s(10)}px;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #timingCheckbox::indicator {{
                width: {_s(16)}px;
                height: {_s(16)}px;
                border-radius: {_s(4)}px;
                border: 1px solid #5d4189;
                background: #0b0a14;
            }}
            #timingCheckbox::indicator:checked {{
                background: #7c3aed;
                border: 1px solid #a855f7;
            }}
            #timingInput {{
                background: #0b0a14;
                color: #f6f3ff;
                border: 1px solid #312049;
                border-radius: {_s(8)}px;
                padding: {_s(8)}px {_s(10)}px;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #timingScroll {{
                background: transparent;
                border: none;
            }}
            #timingScroll QScrollBar:vertical {{
                background: #120d1d;
                width: {_s(10)}px;
                margin: 2px 0 2px {_s(4)}px;
                border-radius: {_s(5)}px;
            }}
            #timingScroll QScrollBar::handle:vertical {{
                background: #5d4189;
                min-height: {_s(24)}px;
                border-radius: {_s(5)}px;
            }}
            #timingScroll QScrollBar::add-line:vertical,
            #timingScroll QScrollBar::sub-line:vertical,
            #timingScroll QScrollBar::add-page:vertical,
            #timingScroll QScrollBar::sub-page:vertical {{
                background: transparent;
                height: 0px;
            }}
            #timingSuffix {{
                color: #b7abd4;
                font: 400 {_s(12)}px "Segoe UI";
            }}
            #perkCard {{
                background: #0a0912;
                border: 1px solid #5d4189;
                border-radius: {_s(12)}px;
            }}
            #perkTitle {{
                color: #f6f3ff;
                font: 700 {_s(16)}px "Segoe UI";
            }}
            #perkSummary {{
                color: #b7abd4;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #augmentRow {{
                background: #27153b;
                border: 1px solid #261938;
                border-radius: {_s(9)}px;
            }}
            #augmentSlot {{
                color: #a855f7;
                font: 700 {_s(10)}px "Segoe UI";
            }}
            #augmentName {{
                color: #f6f3ff;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #footer {{
                background: #0b0a14;
                border: 1px solid #6b479d;
                border-radius: {_s(12)}px;
            }}
            #statusDot {{
                color: #a855f7;
                font: 700 {_s(18)}px "Segoe UI";
            }}
            #statusLabel {{
                color: #f6f3ff;
                font: 400 {_s(15)}px "Segoe UI";
            }}
            #footerDots {{
                color: #a855f7;
                font: 700 {_s(18)}px "Segoe UI";
            }}
            QMenu#scriptMenu {{
                background: #0a0912;
                color: #f6f3ff;
                border: 1px solid #312049;
                padding: {_s(8)}px;
            }}
            QMenu#scriptMenu::item {{
                background: transparent;
                padding: {_s(10)}px {_s(14)}px;
                border: 1px solid #312049;
                margin-bottom: {_s(6)}px;
                font: 400 {_s(14)}px "Segoe UI";
            }}
            QMenu#scriptMenu::item:selected {{
                background: #27153b;
            }}
            #syncButton {{
                background: #0b0a14;
                color: #b7abd4;
                border: 1px solid #312049;
                border-radius: {_s(8)}px;
                padding: {_s(4)}px {_s(10)}px;
                font: 600 {_s(12)}px "Segoe UI";
            }}
            #syncButton:hover {{
                background: #24163a;
                color: #f6f3ff;
                border-color: #7c3aed;
            }}
            #syncButton:pressed {{
                background: #7c3aed;
                color: #ffffff;
                border-color: #a855f7;
            }}
            #syncButton:focus {{
                border-color: #a855f7;
            }}
            #syncButton:disabled {{
                background: #1a1328;
                color: #8f7ab6;
                border-color: #5d4189;
            }}
            """
        )
        self.launch_button.setStyleSheet(self._launch_button_style(active=False))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self.titlebar.geometry().contains(event.position().toPoint()):
            if not self.isMaximized():
                self.drag_origin = event.globalPosition().toPoint()
                self.start_window_pos = self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.drag_origin is not None and self.start_window_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self.drag_origin
            self.move(self.start_window_pos + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self.drag_origin = None
        self.start_window_pos = None
        super().mouseReleaseEvent(event)

    def _start_sync(self) -> None:
        self.sync_button.setEnabled(False)
        self.sync_button.setText("Syncing...")
        self.status_label.setText("Status: Checking for script updates...")
        QApplication.processEvents()
        thread = threading.Thread(target=self._run_sync, daemon=True)
        thread.start()

    def _run_sync(self) -> None:
        result = sync_scripts()
        self.sync_completed.emit(result)

    def _on_sync_done(self, result: SyncResult) -> None:
        self.sync_button.setEnabled(True)
        self.sync_button.setText("Sync")
        previous_selected_id = self.selected.id if self.selected is not None else None
        self._reload_definitions()
        self.global_keybinds = self._build_global_keybinds()
        self._apply_saved_keybinds()
        self._populate_script_menu()

        if previous_selected_id is not None:
            restored = next((item for item in self.definitions if item.id == previous_selected_id), None)
            if restored is not None:
                self._show_definition(restored)
            else:
                self._clear_selection()
        else:
            self._clear_selection()

        if not self.definitions and not result.errors:
            self.status_label.setText("Status: No downloaded scripts available yet")
            return
        self.status_label.setText(f"Status: {result.summary()}")
        if result.errors and not result.changed:
            detail = "\n".join(result.errors[:5])
            QMessageBox.warning(
                self,
                "Script sync failed",
                f"Scripts could not be downloaded from GitHub. Click 'Sync' to retry.\n\nDetails:\n{detail}",
            )

    def _start_drag(self, _event) -> None:
        pass

    def _on_drag(self, _event) -> None:
        pass

    def _minimize_window(self) -> None:
        self.showMinimized()

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.max_button.setText("[]")
        else:
            self.showMaximized()
            self.max_button.setText("o")


def launch() -> None:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)

    global _SF
    screen = app.primaryScreen()
    if screen:
        available_h = screen.availableGeometry().height()
        _SF = min(1.0, max(0.65, available_h / _DESIGN_H))

    app.setStyle("Fusion")
    ui_font = QFont("Segoe UI", max(8, int(11 * _SF)))
    ui_font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(ui_font)
    app.setQuitOnLastWindowClosed(True)
    window = OffLimitsWindow()
    window.show()
    if owns_app:
        app.exec()

