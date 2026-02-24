from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QSizePolicy,
)


class GenerationProgressBar(QWidget):
    """Compact progress bar showing step count and current node name."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self._node_label = QLabel("Idle", self)
        self._node_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._node_label.setMinimumWidth(140)

        self._bar = QProgressBar(self)
        self._bar.setRange(0, 1)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFixedHeight(16)
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._step_label = QLabel("", self)
        self._step_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._step_label.setMinimumWidth(60)

        layout.addWidget(self._node_label)
        layout.addWidget(self._bar)
        layout.addWidget(self._step_label)

    # ------------------------------------------------------------------
    # Public interface (connected to WebSocketClient signals)
    # ------------------------------------------------------------------

    def on_progress(self, prompt_id: str, value: int, maximum: int, node_id: str) -> None:
        self._bar.setRange(0, maximum)
        self._bar.setValue(value)
        self._step_label.setText(f"{value}/{maximum}")

    def on_node_executing(self, prompt_id: str, node_id: str) -> None:
        self._node_label.setText(f"Node {node_id}")

    def on_execution_started(self, prompt_id: str) -> None:
        self._bar.setRange(0, 1)
        self._bar.setValue(0)
        self._step_label.setText("")
        self._node_label.setText("Starting…")

    def on_execution_finished(self, prompt_id: str) -> None:
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        self._step_label.setText("Done")
        self._node_label.setText("Finished")

    def on_execution_error(self, prompt_id: str, message: str) -> None:
        self._bar.setRange(0, 1)
        self._bar.setValue(0)
        self._node_label.setText("Error")
        self._step_label.setText("")

    def reset(self) -> None:
        self._bar.setRange(0, 1)
        self._bar.setValue(0)
        self._step_label.setText("")
        self._node_label.setText("Idle")
