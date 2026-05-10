from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading

from PySide6.QtCore import QPoint, Qt, QSize, Signal, QTimer
from PySide6.QtGui import QAction, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .definitions import (
    AugmentDefinition,
    KeybindDefinition,
    PerkDefinition,
    ScriptDefinition,
    SharedPerksDefinition,
    TimingDefinition,
    load_definitions,
    load_shared_perks,
)
from .gpc import (
    ACTION_LABELS,
    build_gpc_script,
    default_export_path,
    get_export_required_actions,
    get_button_choices,
    get_default_action_map,
    get_platform_choices,
    get_toggle_combo_choices,
)
from .runtime import (
    active_scripts_json_path,
    build_command,
    current_ahk_runtime_label,
    format_keybind_display,
    keybind_settings_path,
    launch_script,
    managed_runtime_dir,
    normalize_keybind_value,
    project_root,
    resolve_entry,
    resources_root,
    stop_managed_ahk_scripts,
    stop_process,
)
from .tester import TESTER_TARGET_TITLE, TesterTargetWindow
from .updater import SyncResult, sync_scripts
from .version import APP_VERSION

# Design resolution height â€” all pixel constants are authored at this size.
_DESIGN_H = 1020
_SF: float = 1.0


def _s(n: int) -> int:
    """Scale a pixel value by the current screen scale factor."""
    return max(1, int(n * _SF))


class ElidedLabel(QLabel):
    """QLabel that elides text with '...' instead of hard-clipping."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setText(text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = text
        self._update_elide()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self) -> None:
        if not hasattr(self, "_full_text"):
            return
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, self.width())
        if elided != QLabel.text(self):
            QLabel.setText(self, elided)


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
        self.titlebar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
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
        self.body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
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
            QComboBox#timingInput {{
                padding-right: {_s(28)}px;
            }}
            QComboBox#timingInput::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: {_s(26)}px;
                border: none;
                background: transparent;
            }}
            QComboBox#timingInput QAbstractItemView {{
                background: {self.colors["panel_alt"]};
                color: {self.colors["text"]};
                border: 1px solid #6b479d;
                selection-background-color: {self.colors["hover"]};
                selection-color: {self.colors["text"]};
                outline: 0;
                padding: {_s(4)}px;
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


class ThemedMessageDialog(ThemedDialog):
    def __init__(self, title: str, message: str, level: str, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(title, colors, parent)
        self.resize(_s(520), _s(280))

        accent_colors = {
            "info": colors["accent"],
            "warning": "#f59e0b",
            "error": "#ef4444",
        }
        accent = accent_colors.get(level, colors["accent"])

        card = QFrame()
        card.setObjectName("dialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(_s(16), _s(16), _s(16), _s(16))
        card_layout.setSpacing(_s(12))
        self.body_layout.addWidget(card)

        badge = QLabel(level.upper())
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"""
            QLabel {{
                background: {accent};
                color: #ffffff;
                border-radius: {_s(8)}px;
                padding: {_s(6)}px {_s(10)}px;
                font: 700 {_s(11)}px "Segoe UI";
            }}
            """
        )
        card_layout.addWidget(badge, 0, Qt.AlignLeft)

        body = QLabel(message)
        body.setObjectName("dialogHint")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card_layout.addWidget(body)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        ok = QPushButton("OK")
        ok.setObjectName("dialogSaveButton")
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)

        self.body_layout.addLayout(buttons)


class OffLimitsWindow(QMainWindow):
    sync_completed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(_s(1460), _s(1120))
        self.setMinimumSize(_s(1360), _s(1080))

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
        self.running_in_tester = False
        self.tester_script_active = False
        self.selected_options_dirty = False
        self.running_option_overrides: dict[str, str] = {}
        self.current_launch_extra_args: list[str] = []
        self.current_target_label = "Game"
        self.last_exit_unexpected = False
        self.tester_marker_file: Path | None = None
        self.tester_marker_offset = 0
        self.timing_inputs: dict[str, QWidget] = {}
        self.global_keybind_inputs: dict[str, QLineEdit] = {}
        self.gpc_action_inputs: dict[str, QComboBox] = {}
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
        self.tester_target = TesterTargetWindow(self.colors, self)
        self.tester_target.event_captured.connect(self._on_tester_event)
        self.tester_target.visibility_changed.connect(self._on_tester_target_visibility_changed)
        self.marker_poll_timer = QTimer(self)
        self.marker_poll_timer.setInterval(200)
        self.marker_poll_timer.timeout.connect(self._poll_tester_marker_file)
        self.last_version_notice: str = ""

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

    def _show_popup(self, level: str, title: str, message: str) -> None:
        dialog = ThemedMessageDialog(title, message, level, self.colors, self)
        dialog.exec()

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

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        body_layout.addWidget(self.tabs)

        main_tab = QWidget()
        main_layout = QVBoxLayout(main_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(_s(14))
        self.tabs.addTab(main_tab, "Main")

        top_row = QHBoxLayout()
        top_row.setSpacing(_s(12))
        top_row.setAlignment(Qt.AlignTop)
        main_layout.addLayout(top_row, 1)

        self.selector_panel = self._build_selector_panel()
        self.selector_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top_row.addWidget(self.selector_panel, 1)

        self.requirements_panel = self._build_requirements_panel()
        self.requirements_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        top_row.addWidget(self.requirements_panel, 1)

        self.perks_panel = self._build_perks_panel()
        main_layout.addWidget(self.perks_panel, 0)

        self.footer = self._build_footer()
        main_layout.addWidget(self.footer)

        self.tabs.addTab(self._build_tester_tab(), "Tester")

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

        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setObjectName("subtitleLabel")
        title_left.addWidget(version_label)

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

        self.setup_preview_button = QPushButton("IMG")
        self.setup_preview_button.setObjectName("previewImageButton")
        self.setup_preview_button.setCursor(Qt.PointingHandCursor)
        self.setup_preview_button.setFixedSize(_s(78), _s(78))
        self.setup_preview_button.clicked.connect(self._open_setup_preview)
        self._configure_preview_button(
            self.setup_preview_button,
            "pictures/Spot.png",
            QSize(_s(70), _s(70)),
        )
        top.addWidget(self.setup_preview_button, 0, Qt.AlignTop)

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

        header = self._section_header("Perks & Augments", "", right_small=True)
        layout.addWidget(header)

        groups = QWidget()
        self.perk_groups_layout = QHBoxLayout(groups)
        self.perk_groups_layout.setContentsMargins(0, 0, 0, 0)
        self.perk_groups_layout.setSpacing(_s(18))
        layout.addWidget(groups)

        self.required_perks_group = QFrame()
        self.required_perks_group.setObjectName("innerCard")
        required_group_layout = QVBoxLayout(self.required_perks_group)
        required_group_layout.setContentsMargins(_s(14), _s(14), _s(14), _s(14))
        required_group_layout.setSpacing(_s(12))
        self.perk_groups_layout.addWidget(self.required_perks_group, 1)

        self.required_perks_label = QLabel("Required Perks")
        self.required_perks_label.setObjectName("requirementsTitle")
        required_group_layout.addWidget(self.required_perks_label)

        self.required_perk_row = QWidget()
        self.required_perk_row_layout = QHBoxLayout(self.required_perk_row)
        self.required_perk_row_layout.setContentsMargins(0, 0, 0, 0)
        self.required_perk_row_layout.setSpacing(_s(12))
        required_group_layout.addWidget(self.required_perk_row)

        self.recommended_perks_group = QFrame()
        self.recommended_perks_group.setObjectName("innerCard")
        recommended_group_layout = QVBoxLayout(self.recommended_perks_group)
        recommended_group_layout.setContentsMargins(_s(14), _s(14), _s(14), _s(14))
        recommended_group_layout.setSpacing(_s(12))
        self.perk_groups_layout.addWidget(self.recommended_perks_group, 1)

        self.recommended_perks_label = QLabel("Recommended Perks")
        self.recommended_perks_label.setObjectName("requirementsTitle")
        recommended_group_layout.addWidget(self.recommended_perks_label)

        self.recommended_perk_row = QWidget()
        self.recommended_perk_row_layout = QHBoxLayout(self.recommended_perk_row)
        self.recommended_perk_row_layout.setContentsMargins(0, 0, 0, 0)
        self.recommended_perk_row_layout.setSpacing(_s(12))
        recommended_group_layout.addWidget(self.recommended_perk_row)

        return panel

    def _build_tester_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_s(14))

        top_row = QHBoxLayout()
        top_row.setSpacing(_s(12))
        top_row.setAlignment(Qt.AlignTop)
        layout.addLayout(top_row, 1)

        control_panel = self._panel()
        control_layout = control_panel.layout()
        control_layout.addWidget(self._section_header("Tester Controls", "[ ]"))

        control_card = self._inner_card()
        control_inner = control_card.layout()
        control_layout.addWidget(control_card)

        intro = QLabel(
            "Launch the selected script against a dedicated tester window instead of the game. Keyboard input is captured once that window is focused. Mouse clicks are only logged when your cursor is over the tester surface."
        )
        intro.setObjectName("requirementsDesc")
        intro.setWordWrap(True)
        control_inner.addWidget(intro)

        self.tester_target_status_label = QLabel(f"Target Window: {TESTER_TARGET_TITLE} (closed)")
        self.tester_target_status_label.setObjectName("testerMeta")
        control_inner.addWidget(self.tester_target_status_label)

        self.tester_toggle_key_label = QLabel("Toggle Key: -")
        self.tester_toggle_key_label.setObjectName("testerMeta")
        control_inner.addWidget(self.tester_toggle_key_label)

        self.tester_last_interval_label = QLabel("Last Interval: -")
        self.tester_last_interval_label.setObjectName("testerMeta")
        control_inner.addWidget(self.tester_last_interval_label)

        self.tester_pressed_label = QLabel("Pressed Now: None")
        self.tester_pressed_label.setObjectName("testerMeta")
        control_inner.addWidget(self.tester_pressed_label)

        self.tester_last_input_label = QLabel("Last Input: None")
        self.tester_last_input_label.setObjectName("testerMeta")
        self.tester_last_input_label.setWordWrap(True)
        control_inner.addWidget(self.tester_last_input_label)

        preview_title = QLabel("Effective Launch Preview")
        preview_title.setObjectName("timingTitle")
        control_inner.addWidget(preview_title)

        self.tester_preview_label = QLabel("No script selected.")
        self.tester_preview_label.setObjectName("testerPreview")
        self.tester_preview_label.setWordWrap(True)
        self.tester_preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        control_inner.addWidget(self.tester_preview_label)

        open_button = QPushButton("Open Tester Window")
        open_button.setObjectName("testerActionButton")
        open_button.clicked.connect(self._open_tester_target)
        control_inner.addWidget(open_button)

        focus_button = QPushButton("Focus Tester Window")
        focus_button.setObjectName("testerGhostButton")
        focus_button.clicked.connect(self._focus_tester_target)
        control_inner.addWidget(focus_button)

        launch_button = QPushButton("Launch In Tester")
        launch_button.setObjectName("testerPrimaryButton")
        launch_button.clicked.connect(self._launch_selected_in_tester)
        control_inner.addWidget(launch_button)

        clear_button = QPushButton("Clear Tester Log")
        clear_button.setObjectName("testerGhostButton")
        clear_button.clicked.connect(self._clear_tester_log)
        control_inner.addWidget(clear_button)

        control_layout.addStretch(1)
        top_row.addWidget(control_panel, 1)

        log_panel = self._panel()
        log_layout = log_panel.layout()
        log_layout.addWidget(self._section_header("Captured Inputs", "ms"))

        log_card = self._inner_card()
        log_inner = log_card.layout()
        log_layout.addWidget(log_card)

        self.tester_log = QListWidget()
        self.tester_log.setObjectName("testerLog")
        log_inner.addWidget(self.tester_log)

        top_row.addWidget(log_panel, 1)
        return page

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

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(_s(8))

        self.export_gpc_button = QPushButton("Export Selected as GPC")
        self.export_gpc_button.setObjectName("footerActionButton")
        self.export_gpc_button.setCursor(Qt.PointingHandCursor)
        self.export_gpc_button.clicked.connect(self._export_selected_gpc)
        actions_layout.addWidget(self.export_gpc_button)

        self.stop_all_button = QPushButton("Stop All Scripts")
        self.stop_all_button.setObjectName("footerActionButton")
        self.stop_all_button.setCursor(Qt.PointingHandCursor)
        self.stop_all_button.clicked.connect(self._stop_all_scripts)
        actions_layout.addWidget(self.stop_all_button)

        self.sync_button = QPushButton("Sync")
        self.sync_button.setObjectName("syncButton")
        self.sync_button.setCursor(Qt.PointingHandCursor)
        self.sync_button.setToolTip("Re-download scripts from GitHub")
        self.sync_button.clicked.connect(self._start_sync)
        actions_layout.addWidget(self.sync_button)

        layout.addWidget(actions, 0, Qt.AlignRight)

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

    def _clear_perk_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_perk_row(self, layout, perks: list[PerkDefinition], center: bool = False) -> None:
        self._clear_perk_layout(layout)
        if center:
            layout.addStretch(1)
        for perk in perks:
            fw = _s(230) if center else None
            layout.addWidget(self._build_perk_card(perk, fixed_width=fw))
        layout.addStretch(1)

    def _render_perks(self) -> None:
        self._render_perk_row(self.required_perk_row_layout, self.shared_perks.required)
        self._render_perk_row(self.recommended_perk_row_layout, self.shared_perks.recommended, center=True)
        self.required_perks_group.setVisible(bool(self.shared_perks.required))
        self.recommended_perks_group.setVisible(bool(self.shared_perks.recommended))
        req_n = max(1, len(self.shared_perks.required))
        rec_n = max(1, len(self.shared_perks.recommended))
        self.perk_groups_layout.setStretch(0, req_n)
        self.perk_groups_layout.setStretch(1, rec_n)

    def _build_perk_card(self, perk: PerkDefinition, fixed_width: int | None = None) -> QWidget:
        card = QFrame()
        card.setObjectName("perkCard")
        card.setFixedHeight(_s(224))
        if fixed_width is not None:
            card.setFixedWidth(fixed_width)
            card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        else:
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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
        layout.setContentsMargins(_s(8), _s(7), _s(8), _s(7))
        layout.setSpacing(_s(8))

        slot = QLabel(augment.slot.upper())
        slot.setObjectName("augmentSlot")
        slot.setFixedWidth(_s(46))
        layout.addWidget(slot)

        icon = QLabel()
        icon.setPixmap(self._load_pixmap(augment.image, _s(18), _s(18)))
        icon.setFixedSize(_s(18), _s(18))
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        name = ElidedLabel(augment.name)
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
            checkbox.toggled.connect(lambda _checked, control=checkbox, key=timing.key: self._on_timing_control_edited(control, key))
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
        entry.textEdited.connect(lambda _text, control=entry, key=timing.key: self._on_timing_control_edited(control, key))
        entry.returnPressed.connect(self._relaunch_selected_from_inputs)
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
        if hasattr(self, "tester_toggle_key_label"):
            self._refresh_tester_key_summary()

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
        if hasattr(self, "tester_toggle_key_label"):
            self._refresh_tester_key_summary()

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
            self._show_popup(
                "info",
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
        self.selected_options_dirty = False
        self.running_option_overrides = {}
        self.current_target_label = "Game"
        self.game_button.setText("Black Ops 7 Zombies")
        self.selected_script_label.setText("Selected Script: None")
        self.status_label.setText("Status: Idle")
        self._refresh_setup(None)
        self._refresh_timings(None)
        self._refresh_tester_key_summary()
        self._refresh_target_summary()
        self._refresh_health_summary()
        self._refresh_pending_changes_summary()
        self._refresh_tester_preview()
        self._refresh_launch_state()

    def _show_definition(self, definition: ScriptDefinition) -> None:
        if self._has_running_script() and self.running_definition is not None and self.running_definition.id != definition.id:
            result = self._stop_running_script()
            if not result.ok:
                self.status_label.setText(f"Status: {result.message}")
                self._show_popup("error", "Stop failed", result.message)
                self._refresh_launch_state()
                return
        elif self.running_definition is not None and self.running_definition.id != definition.id:
            stop_managed_ahk_scripts(self.definitions)
            self.running_process = None
            self.running_definition = None

        self.selected = definition
        self.selected_options_dirty = False
        self.game_button.setText(definition.name)
        self.selected_script_label.setText(f"Selected Script: {definition.name}")
        if self._is_selected_running():
            self.status_label.setText(f"Status: Running {definition.name}")
        else:
            self.status_label.setText(f"Status: Ready to launch {definition.name}")
        self._refresh_setup(definition)
        self._refresh_timings(definition)
        self._refresh_tester_key_summary()
        self._refresh_target_summary()
        self._refresh_health_summary()
        self._refresh_pending_changes_summary()
        self._refresh_tester_preview()
        self._refresh_launch_state()

    def _refresh_launch_state(self) -> None:
        if self._is_selected_running():
            self.launch_button.setText("Relaunch Script" if self.selected_options_dirty else "End Script")
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
        self.export_gpc_button.setEnabled(self.selected is not None)
        self.stop_all_button.setEnabled(self._has_running_script() or self.selected is not None)
        self._refresh_pending_changes_summary()
        self._refresh_health_summary()
        self._refresh_target_summary()
        self._refresh_tester_preview()

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
            "Upgrade your gun as much as possible, goal is to kill the zombies with 1 shot.",
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

        tips_header = QWidget()
        tips_header_layout = QHBoxLayout(tips_header)
        tips_header_layout.setContentsMargins(0, 0, 0, 0)
        tips_header_layout.setSpacing(_s(10))

        tips_label = QLabel("Tips")
        tips_label.setObjectName("timingTitle")
        tips_header_layout.addWidget(tips_label, 0, Qt.AlignVCenter)

        tips_line = QFrame()
        tips_line.setObjectName("dividerLine")
        tips_line.setFixedHeight(1)
        tips_header_layout.addWidget(tips_line, 1, Qt.AlignVCenter)
        self.setup_layout.addWidget(tips_header)

        tips_row = QWidget()
        tips_row_layout = QHBoxLayout(tips_row)
        tips_row_layout.setContentsMargins(0, 0, 0, 0)
        tips_row_layout.setSpacing(_s(10))

        bullet = QLabel("*")
        bullet.setObjectName("setupBullet")
        tips_row_layout.addWidget(bullet, 0, Qt.AlignTop)

        tip_text = QLabel("Keep this door CLOSED for the fastest spawns")
        tip_text.setObjectName("setupItem")
        tip_text.setWordWrap(True)
        tips_row_layout.addWidget(tip_text, 1, Qt.AlignTop)

        tip_image_button = QPushButton("IMG")
        tip_image_button.setObjectName("tipImageButton")
        tip_image_button.setCursor(Qt.PointingHandCursor)
        tip_image_button.setFixedSize(_s(56), _s(42))
        tip_image_button.setToolTip("Click to enlarge")
        tip_image_button.clicked.connect(self._open_setup_preview)
        self._configure_preview_button(
            tip_image_button,
            "pictures/Closed.png",
            QSize(_s(50), _s(36)),
        )
        tips_row_layout.addWidget(tip_image_button, 0, Qt.AlignTop)

        self.setup_layout.addWidget(tips_row)

    def _open_setup_preview(self) -> None:
        dialog = ThemedDialog("Setup Preview", self.colors, self)
        dialog.resize(self.size())
        dialog.body_layout.setContentsMargins(_s(8), _s(8), _s(8), _s(8))
        dialog.body_layout.setSpacing(0)

        preview = QLabel()
        preview.setObjectName("previewText")
        preview.setAlignment(Qt.AlignCenter)
        preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview.setStyleSheet(
            f"""
            QLabel {{
                background: #120d1d;
                color: #a855f7;
                border: 1px solid #5a3d86;
                border-radius: {_s(12)}px;
                font: 700 {_s(32)}px "Segoe UI";
            }}
            """
        )
        button = self.sender()
        image_path = button.property("preview_image") if isinstance(button, QPushButton) else ""
        target_width = max(_s(440), self.width() - _s(80))
        target_height = max(_s(300), self.height() - _s(160))
        pixmap = self._load_pixmap(str(image_path), target_width, target_height)
        if not pixmap.isNull():
            preview.setPixmap(pixmap)
        else:
            preview.setText("IMG")
        dialog.body_layout.addWidget(preview)

        dialog.exec()

    def _configure_preview_button(self, button: QPushButton, relative_path: str, icon_size: QSize) -> None:
        button.setProperty("preview_image", relative_path)
        pixmap = self._load_pixmap(relative_path, icon_size.width(), icon_size.height())
        if pixmap.isNull():
            return
        button.setText("")
        button.setIcon(QIcon(pixmap))
        button.setIconSize(icon_size)

    def _refresh_timings(self, definition: ScriptDefinition | None) -> None:
        while self.timing_layout.count():
            item = self.timing_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.timing_inputs = {}

        if definition is None or not definition.timings:
            self.selector_variables_empty.show()
            self._update_dirty_control_states()
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
        self._update_dirty_control_states()

    def _launch_selected(self) -> None:
        if self.selected is None:
            self._show_popup("warning", "No script", "Pick script first.")
            return

        errors = self._validate_selected_launch()
        if errors:
            self.status_label.setText("Status: Launch validation failed")
            self._show_popup("warning", "Launch validation", "\n".join(errors[:6]))
            return

        if self._is_selected_running():
            if self.selected_options_dirty:
                self._relaunch_selected_from_inputs()
                return
            result = self._stop_running_script()
            if result.ok:
                self.status_label.setText(f"Status: Stopped {self.selected.name}")
            else:
                self.status_label.setText(f"Status: {result.message}")
                self._show_popup("error", "Stop failed", result.message)
            self._refresh_launch_state()
            return

        self._start_selected_script(restart_selected=False)

    def _launch_selected_in_tester(self) -> None:
        if self.selected is None:
            self._show_popup("warning", "No script", "Pick script first.")
            return

        errors = self._validate_selected_launch()
        if errors:
            self.status_label.setText("Status: Launch validation failed")
            self._show_popup("warning", "Launch validation", "\n".join(errors[:6]))
            return

        self._open_tester_target()
        marker_dir = managed_runtime_dir() / "tester_markers"
        marker_dir.mkdir(parents=True, exist_ok=True)
        self.tester_marker_file = marker_dir / "current_marker.log"
        self.tester_marker_file.write_text("", encoding="utf-8")
        self.tester_marker_offset = 0
        self._start_selected_script(
            restart_selected=False,
            extra_args=[
                "--target-title",
                self.tester_target.target_selector(),
                "--marker-file",
                str(self.tester_marker_file),
            ],
        )
        QApplication.processEvents()
        self.status_label.setText(f"Status: Running {self.selected.name} in tester")
        self.tester_target.focus_label.setText("Status: Script launched. Press your toggle key in this window.")
        QTimer.singleShot(150, self._focus_tester_target)

    def _open_tester_target(self) -> None:
        self.tester_target.open_and_focus()
        self._set_tester_target_status(opened=True)

    def _focus_tester_target(self) -> None:
        self.tester_target.open_and_focus()
        self._set_tester_target_status(opened=True)

    def _clear_tester_log(self) -> None:
        self.tester_log.clear()
        self.tester_target.clear_state()
        self.tester_script_active = False
        self.tester_last_interval_label.setText("Last Interval: -")
        self.tester_pressed_label.setText("Pressed Now: None")
        self.tester_last_input_label.setText("Last Input: None")

    def _poll_tester_marker_file(self) -> None:
        if self.tester_marker_file is None or not self.tester_marker_file.exists():
            return
        try:
            with self.tester_marker_file.open("r", encoding="utf-8") as handle:
                handle.seek(self.tester_marker_offset)
                chunk = handle.read()
                self.tester_marker_offset = handle.tell()
        except Exception:
            return
        for line in chunk.splitlines():
            marker = line.strip()
            if not marker:
                continue
            self._handle_tester_marker(marker)

    def _handle_tester_marker(self, marker: str) -> None:
        if self.running_definition is None:
            return
        if marker == "READY":
            self._add_tester_marker(f"READY: {self.running_definition.name} loaded, press {self._effective_toggle_key_display()} to start")
        elif marker == "START":
            self.tester_script_active = True
            self._add_tester_marker(f"START: {self.running_definition.name}")
        elif marker == "END":
            self.tester_script_active = False
            self._add_tester_marker(f"END: {self.running_definition.name}")
        elif marker == "EXIT":
            self.tester_script_active = False
            self._add_tester_marker(f"EXIT: {self.running_definition.name}")

    def _set_tester_target_status(self, opened: bool) -> None:
        state = "ready" if opened else "closed"
        self.tester_target_status_label.setText(f"Target Window: {TESTER_TARGET_TITLE} ({state})")

    def _on_tester_target_visibility_changed(self, visible: bool) -> None:
        self._set_tester_target_status(opened=visible)

    def _on_tester_event(self, label: str, delta_text: str, pressed_text: str) -> None:
        self.tester_last_input_label.setText(f"Last Input: {label}")
        self.tester_last_interval_label.setText(f"Last Interval: {delta_text}")
        self.tester_pressed_label.setText(f"Pressed Now: {pressed_text}")
        self._insert_tester_log_line(f"{label} | {delta_text} | Active: {pressed_text}")
        while self.tester_log.count() > 250:
            self.tester_log.takeItem(self.tester_log.count() - 1)

    def _insert_tester_log_line(self, text: str) -> None:
        self.tester_log.insertItem(0, text)

    def _add_tester_marker(self, text: str) -> None:
        item = QListWidgetItem(f"========== {text} ==========")
        item.setTextAlignment(Qt.AlignCenter)
        self.tester_log.insertItem(0, item)

    def _effective_toggle_key_display(self) -> str:
        if self.selected is not None:
            for keybind in self.selected.keybinds:
                if keybind.key == "toggle_key":
                    return format_keybind_display(keybind.value)
        return "8"

    def _refresh_tester_key_summary(self) -> None:
        self.tester_toggle_key_label.setText(f"Toggle Key: {self._effective_toggle_key_display()}")
        self._refresh_tester_preview()

    def _export_selected_gpc(self) -> None:
        if self.selected is None:
            self._show_popup("warning", "No script", "Pick script first.")
            return

        if self.selected.gpc is None or not self.selected.gpc.supported:
            self.status_label.setText(f"Status: {self.selected.name} is not exportable to GPC yet")
            self._show_popup(
                "info",
                "GPC export unavailable",
                f"{self.selected.name} does not have GPC export metadata yet.",
            )
            return

        self._open_gpc_export_dialog(self.selected)

    def _open_gpc_export_dialog(self, definition: ScriptDefinition) -> None:
        if definition.gpc is None:
            return

        dialog = ThemedDialog(f"Export {definition.name} as GPC", self.colors, self)
        dialog.resize(_s(680), _s(700))

        card = QFrame()
        card.setObjectName("dialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(_s(14), _s(14), _s(14), _s(14))
        card_layout.setSpacing(_s(12))
        dialog.body_layout.addWidget(card)

        title = QLabel("Cronus Zen Export")
        title.setObjectName("timingTitle")
        card_layout.addWidget(title)

        hint = QLabel("Choose a controller platform, adjust the gameplay action mappings, then save a .gpc file.")
        hint.setObjectName("dialogHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        platform_row = QWidget(dialog)
        platform_layout = QHBoxLayout(platform_row)
        platform_layout.setContentsMargins(0, 0, 0, 0)
        platform_layout.setSpacing(_s(8))
        platform_label = QLabel("Platform")
        platform_label.setObjectName("timingLabel")
        platform_label.setMinimumWidth(_s(150))
        platform_layout.addWidget(platform_label)

        platform_combo = QComboBox()
        platform_combo.setObjectName("timingInput")
        for label, value in get_platform_choices():
            platform_combo.addItem(label, value)
        platform_layout.addWidget(platform_combo, 1)
        card_layout.addWidget(platform_row)

        toggle_row = QWidget(dialog)
        toggle_layout = QHBoxLayout(toggle_row)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(_s(8))
        toggle_label = QLabel("Toggle / Stop Combo")
        toggle_label.setObjectName("timingLabel")
        toggle_label.setMinimumWidth(_s(150))
        toggle_layout.addWidget(toggle_label)

        toggle_combo = QComboBox()
        toggle_combo.setObjectName("timingInput")
        for label, value in get_toggle_combo_choices():
            toggle_combo.addItem(label, value)
        default_toggle = definition.gpc.default_toggle or toggle_combo.currentData()
        index = toggle_combo.findData(default_toggle)
        if index >= 0:
            toggle_combo.setCurrentIndex(index)
        toggle_layout.addWidget(toggle_combo, 1)
        card_layout.addWidget(toggle_row)

        if definition.gpc.notes:
            notes = QLabel("\n".join(f"* {note}" for note in definition.gpc.notes))
            notes.setObjectName("dialogHint")
            notes.setWordWrap(True)
            card_layout.addWidget(notes)

        mapping_title = QLabel("Action Mappings")
        mapping_title.setObjectName("timingTitle")
        card_layout.addWidget(mapping_title)

        self.gpc_action_inputs = {}
        for action in get_export_required_actions(definition):
            row = QWidget(dialog)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(_s(8))

            label = QLabel(ACTION_LABELS.get(action, action.replace("_", " ").title()))
            label.setObjectName("timingLabel")
            label.setMinimumWidth(_s(150))
            row_layout.addWidget(label)

            combo = QComboBox()
            combo.setObjectName("timingInput")
            row_layout.addWidget(combo, 1)
            self.gpc_action_inputs[action] = combo

            card_layout.addWidget(row)

        platform_combo.currentIndexChanged.connect(
            lambda _index, control=platform_combo: self._apply_gpc_platform_defaults(control.currentData())
        )
        self._apply_gpc_platform_defaults(platform_combo.currentData())

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("dialogGhostButton")
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(cancel)

        save = QPushButton("Save GPC")
        save.setObjectName("dialogSaveButton")
        save.clicked.connect(
            lambda: self._save_gpc_export_dialog(
                dialog,
                definition,
                str(platform_combo.currentData()),
                str(toggle_combo.currentData()),
            )
        )
        buttons.addWidget(save)

        dialog.body_layout.addLayout(buttons)
        dialog.exec()

    def _apply_gpc_platform_defaults(self, platform: str) -> None:
        defaults = get_default_action_map(platform)
        choices = get_button_choices(platform)
        for action, combo in self.gpc_action_inputs.items():
            combo.blockSignals(True)
            combo.clear()
            for label, value in choices:
                combo.addItem(label, value)
            default_value = defaults.get(action, "")
            index = combo.findData(default_value)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _save_gpc_export_dialog(
        self,
        dialog: QDialog,
        definition: ScriptDefinition,
        platform: str,
        toggle_combo_id: str,
    ) -> None:
        option_overrides = self._collect_option_overrides()
        action_to_button = {
            action: str(combo.currentData())
            for action, combo in self.gpc_action_inputs.items()
            if combo.currentData() is not None
        }

        try:
            gpc_text = build_gpc_script(
                definition,
                option_overrides,
                platform,
                action_to_button,
                toggle_combo_id,
            )
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"Status: {exc}")
            self._show_popup("error", "GPC export failed", str(exc))
            return

        suggested_path = default_export_path(definition)
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GPC Script",
            str(suggested_path),
            "GPC Scripts (*.gpc);;All Files (*)",
        )
        if not target_path:
            self.status_label.setText("Status: GPC export canceled")
            return

        try:
            Path(target_path).write_text(gpc_text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"Status: Failed to save GPC: {exc}")
            self._show_popup("error", "Save failed", str(exc))
            return

        self.status_label.setText(f"Status: Exported GPC for {definition.name}")
        self._show_popup("info", "GPC exported", f"Saved:\n{target_path}")
        dialog.accept()

    def _collect_option_overrides(self) -> dict[str, str]:
        option_overrides: dict[str, str] = {}
        if self.selected is None:
            return option_overrides

        timing_map = {timing.key: timing for timing in self.selected.timings}
        for key, control in self.timing_inputs.items():
            timing = timing_map[key]
            if isinstance(control, QLineEdit):
                option_overrides[key] = control.text().strip()
            elif isinstance(control, QCheckBox):
                option_overrides[key] = timing.value if control.isChecked() else timing.false_value
        for keybind in self.selected.keybinds:
            option_overrides[keybind.key] = keybind.value
        return option_overrides

    def _current_control_value(self, key: str) -> str:
        control = self.timing_inputs.get(key)
        if control is None or self.selected is None:
            return ""
        timing = next((item for item in self.selected.timings if item.key == key), None)
        if timing is None:
            return ""
        if isinstance(control, QLineEdit):
            return control.text().strip()
        if isinstance(control, QCheckBox):
            return timing.value if control.isChecked() else timing.false_value
        return ""

    def _dirty_option_keys(self) -> list[str]:
        if self.selected is None:
            return []
        if not self.running_option_overrides:
            return []
        dirty: list[str] = []
        for timing in self.selected.timings:
            if self._current_control_value(timing.key) != self.running_option_overrides.get(timing.key, ""):
                dirty.append(timing.label)
        return dirty

    def _update_dirty_control_states(self) -> None:
        if self.selected is None:
            return
        dirty_labels = set(self._dirty_option_keys())
        for timing in self.selected.timings:
            control = self.timing_inputs.get(timing.key)
            if control is None:
                continue
            is_dirty = timing.label in dirty_labels
            control.setProperty("dirty", is_dirty)
            control.style().unpolish(control)
            control.style().polish(control)

    def _refresh_pending_changes_summary(self) -> None:
        if not hasattr(self, "pending_changes_label"):
            return
        dirty = self._dirty_option_keys()
        if not dirty:
            self.pending_changes_label.setText("Pending Changes: None")
            return
        self.pending_changes_label.setText(f"Pending Changes: {', '.join(dirty)}")

    def _refresh_target_summary(self) -> None:
        if not hasattr(self, "launch_target_label"):
            return
        self.launch_target_label.setText(f"Target: {self.current_target_label}")

    def _refresh_health_summary(self) -> None:
        if not hasattr(self, "launch_health_label"):
            return
        if self._has_running_script():
            mode = "Running in tester" if self.running_in_tester else "Running"
            self.launch_health_label.setText(f"Health: {mode}")
        elif self.last_exit_unexpected:
            self.launch_health_label.setText("Health: Exited unexpectedly")
        else:
            self.launch_health_label.setText("Health: Not running")

    def _build_preview_extra_args(self) -> list[str]:
        preview_marker = managed_runtime_dir() / "tester_markers" / "current_marker.log"
        return [
            "--target-title",
            self.tester_target.target_selector(),
            "--marker-file",
            str(preview_marker),
        ]

    def _refresh_tester_preview(self) -> None:
        if self.selected is None:
            self.tester_preview_label.setText("No script selected.")
            return

        option_overrides = self._collect_option_overrides()
        extra_args = self._build_preview_extra_args()
        lines = [
            f"Script: {self.selected.name}",
            f"Target: Tester",
            f"Toggle: {self._effective_toggle_key_display()}",
            f"Exit: {format_keybind_display(option_overrides.get('exit_key', 'F2'))}",
            f"Scoreboard: {'On' if option_overrides.get('scoreboard_toggling', '1') not in {'0', 'false', 'False'} else 'Off'}",
        ]
        try:
            command = build_command(self.selected, option_overrides, extra_args)
            lines.append("")
            lines.append(subprocess.list2cmdline(command))
        except Exception as exc:  # noqa: BLE001
            lines.append("")
            lines.append(f"Preview unavailable: {exc}")
        self.tester_preview_label.setText("\n".join(lines))

    def _validate_selected_launch(self) -> list[str]:
        errors: list[str] = []
        if self.selected is None:
            errors.append("Pick a script first.")
            return errors

        option_overrides = self._collect_option_overrides()
        toggle_key = option_overrides.get("toggle_key", "").strip()
        exit_key = option_overrides.get("exit_key", "").strip()
        if not toggle_key:
            errors.append("Toggle key is blank.")
        if not exit_key:
            errors.append("Exit key is blank.")
        if toggle_key and exit_key and toggle_key.lower() == exit_key.lower():
            errors.append("Toggle key and exit key cannot be the same.")

        for timing in self.selected.timings:
            if timing.control == "checkbox":
                continue
            value = option_overrides.get(timing.key, "").strip()
            if value == "":
                errors.append(f"{timing.label} is blank.")
                continue
            try:
                int(value)
            except ValueError:
                errors.append(f"{timing.label} must be a whole number.")

        return errors

    def _on_timing_control_edited(self, _control: QWidget, _key: str) -> None:
        self.selected_options_dirty = bool(self._dirty_option_keys())
        self._update_dirty_control_states()
        self._refresh_pending_changes_summary()
        self._refresh_tester_preview()
        if not self._is_selected_running():
            self._refresh_launch_state()
            return
        self._refresh_launch_state()

    def _start_selected_script(self, restart_selected: bool, extra_args: list[str] | None = None) -> None:
        if self._has_running_script():
            if restart_selected or not self._is_selected_running():
                result = self._stop_running_script()
                if not result.ok:
                    self.status_label.setText(f"Status: {result.message}")
                    self._show_popup("error", "Stop failed", result.message)
                    self._refresh_launch_state()
                    return

        stop_managed_ahk_scripts(self.definitions)
        self.running_process = None
        self.running_definition = None

        if not self.keybinds_initialized:
            self.status_label.setText("Status: Click Edit Keybinds and save your keybinds before launch")
            self._show_popup(
                "info",
                "Set keybinds first",
                "Click Edit Keybinds first and save your keybinds so the script uses the correct controls.",
            )
            self._refresh_keybind_button_state()
            return

        option_overrides = self._collect_option_overrides()
        result = launch_script(self.selected, option_overrides, extra_args)
        self.status_label.setText(f"Status: {result.message}")
        if result.ok:
            self.running_process = result.process
            self.running_definition = self.selected
            self.running_in_tester = bool(extra_args and "--target-title" in extra_args)
            self.tester_script_active = False
            self.selected_options_dirty = False
            self.running_option_overrides = option_overrides.copy()
            self.current_launch_extra_args = list(extra_args or [])
            self.current_target_label = "Tester" if self.running_in_tester else "Game"
            self.last_exit_unexpected = False
            if self.running_in_tester and self.tester_marker_file is not None:
                self.marker_poll_timer.start()
            else:
                self.marker_poll_timer.stop()
            self.status_label.setText(f"Status: Running {self.selected.name}")
            self._update_dirty_control_states()
            self._refresh_launch_state()
        else:
            self.running_in_tester = False
            self.current_target_label = "Game"
            self._show_popup("error", "Launch failed", result.message)

    def _relaunch_selected_from_inputs(self) -> None:
        if self.selected is None:
            return
        self._start_selected_script(restart_selected=True, extra_args=list(self.current_launch_extra_args))

    def _has_running_script(self) -> bool:
        if self.running_process is None:
            return False
        if self.running_process.poll() is None:
            return True
        if self.running_in_tester and self.running_definition is not None:
            self._add_tester_marker(f"STOPPED: {self.running_definition.name} process exited")
        self.last_exit_unexpected = self.running_definition is not None
        self.running_in_tester = False
        self.tester_script_active = False
        self.selected_options_dirty = False
        self.running_option_overrides = {}
        self.current_launch_extra_args = []
        self.current_target_label = "Game"
        self.marker_poll_timer.stop()
        self.running_process = None
        self.running_definition = None
        self._update_dirty_control_states()
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
            if self.running_in_tester and self.running_definition is not None:
                stop_label = "END" if self.tester_script_active else "STOPPED"
                self._add_tester_marker(f"{stop_label}: {self.running_definition.name}")
            self.running_process = None
            self.running_definition = None
            self.running_in_tester = False
            self.tester_script_active = False
            self.selected_options_dirty = False
            self.running_option_overrides = {}
            self.current_launch_extra_args = []
            self.current_target_label = "Game"
            self.last_exit_unexpected = False
            self.marker_poll_timer.stop()
            self._update_dirty_control_states()
        return result

    def _stop_all_scripts(self) -> None:
        self._shutdown_scripts()
        self.status_label.setText("Status: Stopped all managed scripts")
        self._refresh_launch_state()

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
            #exportButton {{
                background: #120d1d;
                color: #f6f3ff;
                border: 1px solid #5d4189;
                border-radius: {_s(10)}px;
                padding: {_s(14)}px {_s(18)}px;
                text-align: center;
                font: 600 {_s(14)}px "Segoe UI";
            }}
            #exportButton:hover {{
                background: #1a1328;
                border-color: #a855f7;
            }}
            #exportButton:disabled {{
                color: #7f739c;
                border-color: #312049;
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
            #previewImageButton {{
                background: #120d1d;
                color: #a855f7;
                border: 1px solid #5a3d86;
                border-radius: {_s(12)}px;
                font: 700 {_s(16)}px "Segoe UI";
            }}
            #previewImageButton:hover {{
                background: #1a1328;
                border-color: #a855f7;
            }}
            #previewImageButton:pressed {{
                background: #24163a;
            }}
            #tipImageButton {{
                background: #120d1d;
                color: #a855f7;
                border: 1px solid #5a3d86;
                border-radius: {_s(6)}px;
                font: 700 {_s(10)}px "Segoe UI";
            }}
            #tipImageButton:hover {{
                background: #1a1328;
                border-color: #a855f7;
            }}
            #tipImageButton:pressed {{
                background: #24163a;
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
            #timingCheckbox[dirty="true"] {{
                color: #f6d365;
            }}
            #timingCheckbox::indicator {{
                width: {_s(16)}px;
                height: {_s(16)}px;
                border-radius: {_s(4)}px;
                border: 1px solid #5d4189;
                background: #0b0a14;
            }}
            #timingCheckbox[dirty="true"]::indicator {{
                border: 1px solid #f6d365;
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
            #timingInput[dirty="true"] {{
                border: 1px solid #f6d365;
                background: #1c1524;
            }}
            QComboBox#timingInput {{
                padding-right: {_s(28)}px;
            }}
            QComboBox#timingInput::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: {_s(26)}px;
                border: none;
                background: transparent;
            }}
            QComboBox#timingInput QAbstractItemView {{
                background: #0b0a14;
                color: #f6f3ff;
                border: 1px solid #6b479d;
                selection-background-color: #24163a;
                selection-color: #ffffff;
                outline: 0;
                padding: {_s(4)}px;
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
                font: 400 {_s(12)}px "Segoe UI";
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
            #footerActionButton {{
                background: #0b0a14;
                color: #b7abd4;
                border: 1px solid #312049;
                border-radius: {_s(8)}px;
                padding: {_s(4)}px {_s(10)}px;
                font: 600 {_s(12)}px "Segoe UI";
            }}
            #footerActionButton:hover {{
                background: #24163a;
                color: #f6f3ff;
                border-color: #7c3aed;
            }}
            #footerActionButton:pressed {{
                background: #7c3aed;
                color: #ffffff;
                border-color: #a855f7;
            }}
            #footerActionButton:focus {{
                border-color: #a855f7;
            }}
            #footerActionButton:disabled {{
                background: #1a1328;
                color: #8f7ab6;
                border-color: #5d4189;
            }}
            QTabWidget#mainTabs::pane {{
                border: 1px solid #312049;
                background: #090812;
                border-radius: {_s(12)}px;
                top: -1px;
            }}
            QTabWidget#mainTabs > QWidget {{
                background: transparent;
            }}
            QTabBar::tab {{
                background: #0b0a14;
                color: #b7abd4;
                border: 1px solid #312049;
                border-bottom: none;
                padding: {_s(10)}px {_s(20)}px;
                margin-right: {_s(6)}px;
                border-top-left-radius: {_s(10)}px;
                border-top-right-radius: {_s(10)}px;
                font: 700 {_s(13)}px "Segoe UI";
            }}
            QTabBar::tab:selected {{
                background: #27153b;
                color: #f6f3ff;
                border-color: #7c3aed;
            }}
            QTabBar::tab:hover:!selected {{
                background: #1a1328;
                color: #f6f3ff;
            }}
            #testerMeta {{
                color: #b7abd4;
                font: 400 {_s(13)}px "Segoe UI";
            }}
            #testerPreview {{
                background: #0b0a14;
                color: #f6f3ff;
                border: 1px solid #312049;
                border-radius: {_s(10)}px;
                padding: {_s(10)}px;
                font: 400 {_s(12)}px "Consolas";
            }}
            #testerActionButton {{
                background: #7c3aed;
                color: #f6f3ff;
                border: 1px solid #a855f7;
                border-radius: {_s(10)}px;
                padding: {_s(12)}px;
                font: 700 {_s(14)}px "Segoe UI";
            }}
            #testerActionButton:hover {{
                background: #8b5cf6;
            }}
            #testerPrimaryButton {{
                background: #120d1d;
                color: #f6f3ff;
                border: 1px solid #7c3aed;
                border-radius: {_s(10)}px;
                padding: {_s(12)}px;
                font: 700 {_s(14)}px "Segoe UI";
                text-align: center;
            }}
            #testerPrimaryButton:hover {{
                background: #24163a;
                border-color: #a855f7;
            }}
            #testerPrimaryButton:pressed {{
                background: #7c3aed;
                border-color: #a855f7;
            }}
            #testerGhostButton {{
                background: #0b0a14;
                color: #f6f3ff;
                border: 1px solid #312049;
                border-radius: {_s(10)}px;
                padding: {_s(12)}px;
                font: 700 {_s(14)}px "Segoe UI";
            }}
            #testerGhostButton:hover {{
                background: #24163a;
                border-color: #7c3aed;
            }}
            #testerLog {{
                background: #0b0a14;
                color: #f6f3ff;
                border: 1px solid #312049;
                border-radius: {_s(10)}px;
                padding: {_s(6)}px;
                font: 400 {_s(12)}px "Consolas";
            }}
            #testerLog::item {{
                padding: {_s(6)}px;
                border-bottom: 1px solid #1a1328;
            }}
            #testerLog::item:selected {{
                background: #27153b;
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

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._shutdown_scripts()
        self.tester_target.close()
        super().closeEvent(event)

    def _shutdown_scripts(self) -> None:
        self.marker_poll_timer.stop()
        if self.running_process is not None:
            self._stop_running_script()
        stop_managed_ahk_scripts(self.definitions)

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
            self._maybe_notify_app_update(result)
            return
        self.status_label.setText(f"Status: {result.summary()}")
        self._maybe_notify_app_update(result)
        if result.errors and not result.changed:
            detail = "\n".join(result.errors[:5])
            self._show_popup(
                "warning",
                "Script sync failed",
                f"Scripts could not be downloaded from GitHub. Click 'Sync' to retry.\n\nDetails:\n{detail}",
            )

    def _maybe_notify_app_update(self, result: SyncResult) -> None:
        if not result.app_update_available or not result.latest_version:
            return
        if result.latest_version == self.last_version_notice:
            return

        self.last_version_notice = result.latest_version
        self.status_label.setText(
            f"Status: App update available ({result.current_version} -> {result.latest_version})"
        )
        release_line = f"\n\nDownload: {result.release_url}" if result.release_url else ""
        self._show_popup(
            "info",
            "App update available",
            (
                f"A newer launcher version is available on GitHub.\n\n"
                f"Current version: {result.current_version}\n"
                f"Latest version: {result.latest_version}"
                f"{release_line}"
            ),
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
    app_icon = QIcon(str(resolve_entry("pictures/appicon.png")))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    window = OffLimitsWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    if owns_app:
        app.exec()
