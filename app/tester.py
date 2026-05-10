from __future__ import annotations

import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget


TESTER_TARGET_TITLE = "AFK Tester Target"


def _mouse_button_name(button: Qt.MouseButton) -> str:
    mapping = {
        Qt.LeftButton: "Left Mouse",
        Qt.RightButton: "Right Mouse",
        Qt.MiddleButton: "Middle Mouse",
        Qt.XButton1: "Mouse Button 4",
        Qt.XButton2: "Mouse Button 5",
    }
    if button in mapping:
        return mapping[button]

    raw_value = getattr(button, "value", None)
    if raw_value is None:
        try:
            raw_value = int(button)
        except TypeError:
            raw_value = str(button)
    return f"Mouse Button {raw_value}"


def _key_name(event) -> str:
    text = (event.text() or "").strip()
    if text:
        return text.upper()

    sequence = QKeySequence(event.key()).toString()
    if sequence:
        return sequence.upper()

    return f"KEY {event.key()}"


class TesterCaptureSurface(QFrame):
    key_activity = Signal(str, bool)
    mouse_activity = Signal(str, bool)
    focus_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("testerCaptureSurface")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("Focused input surface")
        title.setObjectName("testerSurfaceTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Focus this window, keep the cursor over this area for mouse tests, and use your script toggle key here."
        )
        hint.setObjectName("testerSurfaceHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.setFocus(Qt.MouseFocusReason)
        if event.button() != Qt.NoButton:
            self.mouse_activity.emit(_mouse_button_name(event.button()), True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.NoButton:
            self.mouse_activity.emit(_mouse_button_name(event.button()), False)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if not event.isAutoRepeat():
            self.key_activity.emit(_key_name(event), True)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # type: ignore[override]
        if not event.isAutoRepeat():
            self.key_activity.emit(_key_name(event), False)
        super().keyReleaseEvent(event)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self.focus_changed.emit(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        self.focus_changed.emit(False)
        super().focusOutEvent(event)


class TesterTargetWindow(QWidget):
    event_captured = Signal(str, str, str)
    visibility_changed = Signal(bool)

    def __init__(self, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colors = colors
        self._last_event_at: float | None = None
        self._pressed_inputs: list[str] = []
        self.drag_origin: QPoint | None = None
        self.start_window_pos: QPoint | None = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(TESTER_TARGET_TITLE)
        self.resize(760, 520)
        self.setMinimumSize(640, 420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("testerShell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        outer.addWidget(self.shell)

        self.titlebar = QFrame()
        self.titlebar.setObjectName("testerTitlebar")
        self.titlebar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        titlebar_layout = QHBoxLayout(self.titlebar)
        titlebar_layout.setContentsMargins(16, 10, 10, 10)
        titlebar_layout.setSpacing(10)
        shell_layout.addWidget(self.titlebar)

        accent = QFrame()
        accent.setObjectName("testerAccent")
        accent.setFixedSize(6, 22)
        titlebar_layout.addWidget(accent, 0, Qt.AlignVCenter)

        title = QLabel("AFK Tester")
        title.setObjectName("testerWindowTitle")
        titlebar_layout.addWidget(title)

        titlebar_layout.addStretch(1)

        min_button = QPushButton("_")
        min_button.setObjectName("testerTitleButton")
        min_button.setCursor(Qt.PointingHandCursor)
        min_button.setFixedSize(34, 26)
        min_button.clicked.connect(self.showMinimized)
        titlebar_layout.addWidget(min_button)

        close_button = QPushButton("X")
        close_button.setObjectName("testerCloseButton")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setFixedSize(34, 26)
        close_button.clicked.connect(self.close)
        titlebar_layout.addWidget(close_button)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.setSpacing(12)
        shell_layout.addWidget(self.body)

        self.focus_label = QLabel("Status: Open and focus this window before toggling a script.")
        self.focus_label.setObjectName("testerWindowMeta")
        self.focus_label.setWordWrap(True)
        body_layout.addWidget(self.focus_label)

        self.capture_surface = TesterCaptureSurface()
        self.capture_surface.key_activity.connect(self._record_key)
        self.capture_surface.mouse_activity.connect(self._record_mouse)
        self.capture_surface.focus_changed.connect(self._update_focus_state)
        body_layout.addWidget(self.capture_surface, 1)

        self.last_event_label = QLabel("Last input: None")
        self.last_event_label.setObjectName("testerWindowMeta")
        body_layout.addWidget(self.last_event_label)

        self.delta_label = QLabel("Interval: -")
        self.delta_label.setObjectName("testerWindowMeta")
        body_layout.addWidget(self.delta_label)

        self.active_label = QLabel("Pressed now: None")
        self.active_label.setObjectName("testerWindowMeta")
        body_layout.addWidget(self.active_label)

        self.setStyleSheet(
            f"""
            QWidget {{
                color: {colors["text"]};
            }}
            #testerShell {{
                background: {colors["panel"]};
                border: 1px solid #6b479d;
                border-radius: 14px;
            }}
            #testerTitlebar {{
                background: {colors["panel_alt"]};
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
                border-bottom: 1px solid #6b479d;
            }}
            #testerAccent {{
                background: {colors["accent"]};
                border-radius: 3px;
            }}
            #testerWindowTitle {{
                color: {colors["text"]};
                font: 700 18px "Segoe UI";
            }}
            #testerWindowMeta {{
                color: {colors["muted"]};
                font: 400 14px "Segoe UI";
            }}
            #testerTitleButton, #testerCloseButton {{
                background: {colors["panel_alt"]};
                color: {colors["text"]};
                border: none;
                border-radius: 8px;
                font: 700 13px "Segoe UI";
            }}
            #testerTitleButton:hover {{
                background: {colors["hover"]};
            }}
            #testerCloseButton:hover {{
                background: {colors["danger_hover"]};
            }}
            #testerCaptureSurface {{
                background: {colors["card"]};
                border: 1px solid {colors["accent"]};
                border-radius: 14px;
            }}
            #testerSurfaceTitle {{
                color: {colors["text"]};
                font: 700 18px "Segoe UI";
            }}
            #testerSurfaceHint {{
                color: {colors["muted"]};
                font: 400 14px "Segoe UI";
            }}
            """
        )

    def target_title(self) -> str:
        return TESTER_TARGET_TITLE

    def target_selector(self) -> str:
        return f"ahk_id {int(self.winId())}"

    def open_and_focus(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, lambda: self.capture_surface.setFocus(Qt.OtherFocusReason))

    def clear_state(self) -> None:
        self._last_event_at = None
        self._pressed_inputs.clear()
        self.last_event_label.setText("Last input: None")
        self.delta_label.setText("Interval: -")
        self.active_label.setText("Pressed now: None")

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

    def showEvent(self, event) -> None:  # type: ignore[override]
        self.visibility_changed.emit(True)
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.visibility_changed.emit(False)
        super().closeEvent(event)

    def _update_focus_state(self, focused: bool) -> None:
        if focused:
            self.focus_label.setText("Status: Focused and ready to capture inputs.")
        else:
            self.focus_label.setText("Status: Click back into the tester surface before running more inputs.")

    def _record_key(self, name: str, pressed: bool) -> None:
        action = "pressed" if pressed else "released"
        self._update_event(f"Key {action}: {name}", name, pressed)

    def _record_mouse(self, name: str, pressed: bool) -> None:
        action = "pressed" if pressed else "released"
        self._update_event(f"Mouse {action}: {name}", name, pressed)

    def _update_event(self, label: str, input_name: str, pressed: bool) -> None:
        now = time.perf_counter()
        if self._last_event_at is None:
            delta_text = "first input"
        else:
            delta_text = f"{((now - self._last_event_at) * 1000):.1f} ms"
        self._last_event_at = now

        if pressed:
            if input_name not in self._pressed_inputs:
                self._pressed_inputs.append(input_name)
        else:
            self._pressed_inputs = [item for item in self._pressed_inputs if item != input_name]

        pressed_text = ", ".join(self._pressed_inputs) if self._pressed_inputs else "None"
        self.last_event_label.setText(f"Last input: {label}")
        self.delta_label.setText(f"Interval: {delta_text}")
        self.active_label.setText(f"Pressed now: {pressed_text}")
        self.event_captured.emit(label, delta_text, pressed_text)
