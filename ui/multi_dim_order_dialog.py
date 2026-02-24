from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QWidget,
)


class MultiDimOrderDialog(QDialog):
    """Let the user set the Cartesian-product loop order for multi-dimensional generation.

    *dims* is a list of ``(label, steps)`` tuples where each *steps* entry is a
    list of node-patch dicts.  The dialog presents them in a reorderable list;
    the topmost entry is the **slowest-varying** (outer) loop and the bottommost
    is the **fastest-varying** (inner) loop.

    After ``exec()`` returns ``Accepted``, call :meth:`ordered_dims` to get the
    reordered list.
    """

    def __init__(
        self,
        dims: list[tuple[str, list[dict]]],
        batch_count: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generation Order")
        self.setMinimumWidth(460)
        self._dims = list(dims)     # working copy — reordered by UI
        self._batch_count = batch_count
        self._build_ui()
        self._refresh_total()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Instruction
        intro = QLabel(
            "Multiple dimensions are active.  Arrange from <b>Slowest</b> (top / outer loop) "
            "to <b>Fastest</b> (bottom / inner loop).  The fastest dimension changes on every job.",
            self,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(intro)

        # List + move buttons side by side
        row = QHBoxLayout()

        self._list = QListWidget(self)
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        self._list.setStyleSheet("QListWidget { font-size: 12px; }")
        for label, steps in self._dims:
            item = QListWidgetItem(f"  {label}  ({len(steps)} option{'s' if len(steps) != 1 else ''})")
            item.setData(Qt.ItemDataRole.UserRole, label)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        row.addWidget(self._list, stretch=1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        self._up_btn = QPushButton("↑  Slower", self)
        self._up_btn.setFixedWidth(90)
        self._up_btn.clicked.connect(self._move_up)
        self._down_btn = QPushButton("↓  Faster", self)
        self._down_btn.setFixedWidth(90)
        self._down_btn.clicked.connect(self._move_down)
        btn_col.addStretch()
        btn_col.addWidget(self._up_btn)
        btn_col.addWidget(self._down_btn)
        btn_col.addStretch()
        row.addLayout(btn_col)
        layout.addLayout(row)

        # Total jobs info
        self._total_label = QLabel("", self)
        self._total_label.setStyleSheet("color: #8ab4d4; font-size: 11px;")
        layout.addWidget(self._total_label)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self._list.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= self._list.count() - 1:
            return
        self._swap_rows(row, row + 1)
        self._list.setCurrentRow(row + 1)

    def _swap_rows(self, a: int, b: int) -> None:
        self._dims[a], self._dims[b] = self._dims[b], self._dims[a]
        item_a = self._list.takeItem(a)
        item_b = self._list.takeItem(b - 1)  # after taking a, b shifts
        self._list.insertItem(a, item_b)
        self._list.insertItem(b, item_a)
        self._refresh_total()

    def _on_rows_moved(self, *_) -> None:
        """Sync self._dims after a drag-drop reorder."""
        label_order = [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
        ]
        dim_map = {label: steps for label, steps in self._dims}
        self._dims = [(lbl, dim_map[lbl]) for lbl in label_order if lbl in dim_map]
        self._refresh_total()

    def _refresh_total(self) -> None:
        total = self._batch_count
        parts: list[str] = []
        for label, steps in self._dims:
            total *= len(steps)
            parts.append(str(len(steps)))
        expr = " × ".join(parts)
        if self._batch_count > 1:
            expr += f" × {self._batch_count} (batch)"
        self._total_label.setText(f"Total jobs queued: {expr} = {total}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ordered_dims(self) -> list[tuple[str, list[dict]]]:
        """Return dims ordered slowest-first (outer loop first)."""
        return list(self._dims)
