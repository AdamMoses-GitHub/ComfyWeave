from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy
)


class _LedIndicator(QLabel):
    """Simple circular LED indicator widget."""

    _COLORS = {
        "grey":   "#666666",
        "yellow": "#f0c040",
        "green":  "#44cc44",
        "red":    "#ee4444",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(14, 14))
        self.set_color("grey")

    def set_color(self, color: str) -> None:
        hex_color = self._COLORS.get(color, "#666666")
        self.setStyleSheet(
            f"background-color: {hex_color}; "
            "border-radius: 7px; "
            "border: 1px solid rgba(0,0,0,0.4);"
        )
        self.setToolTip(color.capitalize())


class ConnectionBar(QWidget):
    """URL input + Connect/Disconnect button + LED status indicator."""

    connect_requested = Signal(str)     # emits the URL string
    disconnect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self._led = _LedIndicator(self)

        self._url_edit = QLineEdit(self)
        self._url_edit.setPlaceholderText("http://127.0.0.1:8188")
        self._url_edit.setText("http://127.0.0.1:8188")
        self._url_edit.setMinimumWidth(200)
        self._url_edit.returnPressed.connect(self._on_button_clicked)

        self._btn = QPushButton("Connect", self)
        self._btn.setFixedWidth(90)
        self._btn.clicked.connect(self._on_button_clicked)

        self._info_label = QLabel("", self)
        self._info_label.setStyleSheet("color: #888; font-size: 11px;")
        self._info_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout.addWidget(self._led)
        layout.addWidget(QLabel("Server:", self))
        layout.addWidget(self._url_edit)
        layout.addWidget(self._btn)
        layout.addWidget(self._info_label)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_url(self, url: str) -> None:
        self._url_edit.setText(url)

    def get_url(self) -> str:
        return self._url_edit.text().strip()

    def set_connecting(self) -> None:
        self._led.set_color("yellow")
        self._led.setToolTip("Connecting…")
        self._btn.setEnabled(False)
        self._btn.setText("…")
        self._url_edit.setEnabled(False)
        self._info_label.setText("Connecting…")

    def set_connected(self, info: str = "") -> None:
        self._connected = True
        self._led.set_color("green")
        self._led.setToolTip("Connected")
        self._btn.setEnabled(True)
        self._btn.setText("Disconnect")
        self._url_edit.setEnabled(False)
        self._info_label.setText(info)

    def set_disconnected(self, error: str = "") -> None:
        self._connected = False
        self._led.set_color("grey" if not error else "red")
        self._led.setToolTip("Disconnected" if not error else error)
        self._btn.setEnabled(True)
        self._btn.setText("Connect")
        self._url_edit.setEnabled(True)
        self._info_label.setText(error or "Disconnected")

    def set_server_info(self, stats: dict) -> None:
        """Populate the info label from a system_stats dict."""
        devices = stats.get("devices", [])
        if devices:
            dev = devices[0]
            name = dev.get("name", "GPU")
            vram_free = dev.get("vram_free", 0)
            vram_total = dev.get("vram_total", 1)
            free_gb = vram_free / 1024 ** 3
            total_gb = vram_total / 1024 ** 3
            info = f"{name}  {free_gb:.1f}/{total_gb:.1f} GB VRAM free"
        else:
            sys_info = stats.get("system", {})
            info = f"ComfyUI {sys_info.get('comfyui_version', '')}"
        self._info_label.setText(info)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_button_clicked(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
        else:
            url = self._url_edit.text().strip()
            if url:
                self.connect_requested.emit(url)
