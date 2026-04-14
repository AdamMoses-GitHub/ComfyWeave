from __future__ import annotations

import random
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QScrollArea, QFrame, QSpinBox, QDoubleSpinBox,
    QTextEdit, QComboBox, QCheckBox, QGroupBox, QSizePolicy,
    QMessageBox, QLineEdit, QCompleter,
    QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QSplitter, QAbstractItemView,
)

from core.workflow import WorkflowManager, EditableNode
from utils.config_manager import ConfigManager
from utils.text_block_manager import TextBlockManager

# Map from ComfyUI input name → model folder queried from /models/{folder}
# Used to decide which server options list applies to each QComboBox field.
_INPUT_TO_FOLDER: dict[str, str] = {
    "lora_name":    "loras",
    "ckpt_name":    "checkpoints",
    "vae_name":     "vae",
    "model_name":   "upscale_models",
    "control_net_name": "controlnet",
    "style_model_name": "style_models",
}

# Input names whose options come from object_info rather than /models/
_OBJECT_INFO_INPUTS = {"sampler_name", "scheduler"}


# ---------------------------------------------------------------------------
# LoRA picker dialog
# ---------------------------------------------------------------------------

class LoRAPickerDialog(QDialog):
    """Searchable checklist dialog for selecting multiple LoRAs."""

    def __init__(
        self,
        choices: list[str],
        preselected: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select LoRAs")
        self.setMinimumSize(420, 520)
        self._choices = choices
        self._selected: set[str] = set(preselected)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Search bar
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search LoRAs…")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Checkable list — ExtendedSelection lets the user Shift/Ctrl+click rows
        # then mass-check or mass-uncheck them via the toolbar buttons below.
        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setToolTip(
            "Click to toggle a single LoRA.\n"
            "Shift+click / Ctrl+click to highlight multiple rows,\n"
            "then use \u2713 Selected / \u2717 Selected to check or uncheck them all."
        )
        for name in self._choices:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in self._selected else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

        # Status + bulk-action row
        bottom_row = QHBoxLayout()
        self._status_lbl = QLabel(self)
        self._status_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self._update_status()
        chk_sel_btn = QPushButton("✓ Selected", self)
        chk_sel_btn.setFixedHeight(24)
        chk_sel_btn.setToolTip("Check all highlighted rows (use Shift/Ctrl+click to highlight multiple)")
        chk_sel_btn.clicked.connect(self._check_selected)
        unchk_sel_btn = QPushButton("✗ Selected", self)
        unchk_sel_btn.setFixedHeight(24)
        unchk_sel_btn.setToolTip("Uncheck all highlighted rows (use Shift/Ctrl+click to highlight multiple)")
        unchk_sel_btn.clicked.connect(self._uncheck_selected)
        sel_all_btn = QPushButton("Select All", self)
        sel_all_btn.setFixedHeight(24)
        sel_all_btn.clicked.connect(self._select_all)
        clr_all_btn = QPushButton("Clear All", self)
        clr_all_btn.setFixedHeight(24)
        clr_all_btn.clicked.connect(self._clear_all)
        bottom_row.addWidget(self._status_lbl)
        bottom_row.addStretch()
        bottom_row.addWidget(chk_sel_btn)
        bottom_row.addWidget(unchk_sel_btn)
        bottom_row.addWidget(sel_all_btn)
        bottom_row.addWidget(clr_all_btn)
        layout.addLayout(bottom_row)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _filter(self, text: str) -> None:
        lowered = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(lowered not in item.text().lower())

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(item.text())
        else:
            self._selected.discard(item.text())
        self._update_status()

    def _select_all(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)

    def _clear_all(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Unchecked)

    def _check_selected(self) -> None:
        for item in self._list.selectedItems():
            item.setCheckState(Qt.CheckState.Checked)

    def _uncheck_selected(self) -> None:
        for item in self._list.selectedItems():
            item.setCheckState(Qt.CheckState.Unchecked)

    def _update_status(self) -> None:
        n = len(self._selected)
        self._status_lbl.setText(f"{n} LoRA{'s' if n != 1 else ''} selected")

    @property
    def selected_loras(self) -> list[str]:
        """Return selected LoRAs in their original list order."""
        return [c for c in self._choices if c in self._selected]


# ---------------------------------------------------------------------------
# LoRA section widget (single-mode combo  OR  multi-mode picker button)
# ---------------------------------------------------------------------------

class LoRASection(QWidget):
    """Replaces the bare QComboBox for lora_name inputs.

    Single mode  (default) — behaves exactly like the normal searchable combo.
    Multi-LoRA mode         — shows a button that opens LoRAPickerDialog; each
                              selected LoRA will trigger a separate generation.
    """

    def __init__(
        self,
        choices: list[str],
        current: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._choices = choices
        # Bootstrap the multi-selection with the workflow’s current value (if valid)
        self._selected_loras: list[str] = [current] if current in choices else []
        self._build_ui(choices, current)

    def _build_ui(self, choices: list[str], current: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(4)

        # Multi-LoRA toggle
        self._multi_cb = QCheckBox("Multi-LoRA Mode", self)
        self._multi_cb.setToolTip(
            "Enable to select multiple LoRAs and run one generation per LoRA."
        )
        self._multi_cb.setStyleSheet("font-size: 11px; color: #8ab4d4;")
        self._multi_cb.toggled.connect(self._on_mode_toggled)
        layout.addWidget(self._multi_cb)

        # Single-mode: editable combo with substring completer
        self._combo = QComboBox(self)
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo.addItems(choices)
        idx = self._combo.findText(current, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        else:
            self._combo.setCurrentText(current)
        completer = QCompleter(choices, self._combo)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._combo.setCompleter(completer)
        self._combo.setToolTip(f"{len(choices)} options (from models/loras)")
        layout.addWidget(self._combo)

        # Multi-mode: picker button (hidden initially)
        self._picker_btn = QPushButton(self._picker_label(), self)
        self._picker_btn.setVisible(False)
        self._picker_btn.clicked.connect(self._open_picker)
        layout.addWidget(self._picker_btn)

    # ------------------------------------------------------------------
    # Mode toggle
    # ------------------------------------------------------------------

    def _on_mode_toggled(self, checked: bool) -> None:
        self._combo.setVisible(not checked)
        self._picker_btn.setVisible(checked)
        if checked and not self._selected_loras:
            # Prime selection with whatever is in the combo
            current = self._combo.currentText()
            if current:
                self._selected_loras = [current]
        self._picker_btn.setText(self._picker_label())

    # ------------------------------------------------------------------
    # Picker dialog
    # ------------------------------------------------------------------

    def _open_picker(self) -> None:
        dlg = LoRAPickerDialog(self._choices, self._selected_loras, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._selected_loras = dlg.selected_loras
            self._picker_btn.setText(self._picker_label())

    def set_single_value(self, value: str) -> None:
        """Restore a saved LoRA value into the combo (single-mode only)."""
        self._combo.setCurrentText(value)

    def _picker_label(self) -> str:
        n = len(self._selected_loras)
        if n == 0:
            return "Select LoRAs…"
        return f"🎛 {n} LoRA{'s' if n != 1 else ''} selected — click to change"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_multi_mode(self) -> bool:
        return self._multi_cb.isChecked()

    def get_value(self) -> str:
        """Always returns a single string suitable for the standard overrides dict."""
        if self._multi_cb.isChecked():
            return self._selected_loras[0] if self._selected_loras else ""
        return self._combo.currentText()

    def get_multi_selection(self) -> list[str] | None:
        """When in multi-mode return the full selection list, else None."""
        if self._multi_cb.isChecked():
            return list(self._selected_loras)
        return None


# ---------------------------------------------------------------------------
# Text block picker dialog
# ---------------------------------------------------------------------------

class TextPickerDialog(QDialog):
    """Full CRUD picker for anonymous per-field text block libraries.

    Presents a split view: left side is a scrollable checklist of saved blocks;
    right side is a full text editor that mirrors the selected block and allows
    inline editing.  OK returns the ordered list of checked blocks for the run.
    """

    def __init__(
        self,
        field_key: str,
        text_mgr: TextBlockManager,
        preselected: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Text Blocks")
        self.setMinimumSize(640, 480)
        self._field_key = field_key
        self._mgr = text_mgr
        self._preselected = set(preselected)
        self._blocks: list[str] = text_mgr.get_blocks(field_key)
        self._current_row: int = -1
        self._ignore_editor_changes = False
        self._build_ui()
        self._refresh_list()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Search bar
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search blocks…")
        self._search.textChanged.connect(self._filter_list)
        layout.addWidget(self._search)

        # Splitter: list left, editor right
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left: checklist
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._list = QListWidget(left)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemChanged.connect(self._on_item_check_changed)
        left_layout.addWidget(self._list)

        # List action buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add", left)
        add_btn.setFixedHeight(24)
        add_btn.clicked.connect(self._add_block)
        del_btn = QPushButton("Delete", left)
        del_btn.setFixedHeight(24)
        del_btn.clicked.connect(self._delete_block)
        up_btn = QPushButton("↑", left)
        up_btn.setFixedWidth(30)
        up_btn.setFixedHeight(24)
        up_btn.clicked.connect(self._move_up)
        dn_btn = QPushButton("↓", left)
        dn_btn.setFixedWidth(30)
        dn_btn.setFixedHeight(24)
        dn_btn.clicked.connect(self._move_down)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        btn_row.addWidget(up_btn)
        btn_row.addWidget(dn_btn)
        left_layout.addLayout(btn_row)

        splitter.addWidget(left)

        # Right: editor
        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        editor_lbl = QLabel("Block content (edits saved automatically):", right)
        editor_lbl.setStyleSheet("color: #888; font-size: 10px;")
        right_layout.addWidget(editor_lbl)
        self._editor = QTextEdit(right)
        self._editor.setPlaceholderText("Select a block on the left to edit it here…")
        self._editor.setEnabled(False)
        self._editor.textChanged.connect(self._on_editor_changed)
        right_layout.addWidget(self._editor)

        splitter.addWidget(right)
        splitter.setSizes([240, 380])
        layout.addWidget(splitter, stretch=1)

        # Selection count
        self._status_lbl = QLabel("", self)
        self._status_lbl.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._status_lbl)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _preview(self, text: str) -> str:
        first_line = text.split("\n")[0].strip()
        return first_line[:80] + ("…" if len(first_line) > 80 else "")

    def _refresh_list(self, selected_row: int = -1) -> None:
        self._ignore_editor_changes = True
        self._list.blockSignals(True)
        filter_text = self._search.text().lower()
        self._list.clear()
        for i, block in enumerate(self._blocks):
            if filter_text and filter_text not in block.lower():
                continue
            item = QListWidgetItem(self._preview(block))
            item.setData(Qt.ItemDataRole.UserRole, i)  # original index
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if block in self._preselected else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._ignore_editor_changes = False
        if selected_row >= 0 and selected_row < self._list.count():
            self._list.setCurrentRow(selected_row)
        elif self._list.count():
            self._list.setCurrentRow(0)
        self._update_status()

    def _filter_list(self) -> None:
        self._refresh_list()

    def _on_row_changed(self, row: int) -> None:
        self._current_row = row
        self._ignore_editor_changes = True
        if row < 0 or row >= self._list.count():
            self._editor.setEnabled(False)
            self._editor.clear()
        else:
            orig_idx = self._list.item(row).data(Qt.ItemDataRole.UserRole)
            self._editor.setEnabled(True)
            self._editor.setPlainText(self._blocks[orig_idx] if orig_idx < len(self._blocks) else "")
        self._ignore_editor_changes = False

    def _on_item_check_changed(self, item: QListWidgetItem) -> None:
        if self._ignore_editor_changes:
            return
        orig_idx = item.data(Qt.ItemDataRole.UserRole)
        block = self._blocks[orig_idx] if orig_idx < len(self._blocks) else ""
        if item.checkState() == Qt.CheckState.Checked:
            self._preselected.add(block)
        else:
            self._preselected.discard(block)
        self._update_status()

    def _on_editor_changed(self) -> None:
        if self._ignore_editor_changes:
            return
        row = self._current_row
        if row < 0 or row >= self._list.count():
            return
        item = self._list.item(row)
        orig_idx = item.data(Qt.ItemDataRole.UserRole)
        if orig_idx >= len(self._blocks):
            return
        old_text = self._blocks[orig_idx]
        new_text = self._editor.toPlainText()
        if new_text == old_text:
            return
        # Update preselected tracking
        if old_text in self._preselected:
            self._preselected.discard(old_text)
            self._preselected.add(new_text)
        # Update local list and persist
        self._blocks[orig_idx] = new_text
        self._mgr.update_block(self._field_key, orig_idx, new_text)
        # Update the list item preview (suppress signals to avoid re-trigger)
        self._list.blockSignals(True)
        item.setText(self._preview(new_text))
        self._list.blockSignals(False)

    def _add_block(self) -> None:
        self._blocks.append("")
        self._mgr.set_blocks(self._field_key, self._blocks)
        new_row = self._list.count()  # will be appended
        self._refresh_list(selected_row=new_row)
        self._editor.setFocus()

    def _delete_block(self) -> None:
        row = self._current_row
        if row < 0 or row >= self._list.count():
            return
        orig_idx = self._list.item(row).data(Qt.ItemDataRole.UserRole)
        if orig_idx < len(self._blocks):
            old_text = self._blocks[orig_idx]
            self._preselected.discard(old_text)
            self._mgr.remove_block(self._field_key, orig_idx)
            self._blocks = self._mgr.get_blocks(self._field_key)
        self._refresh_list(selected_row=min(row, self._list.count() - 1))

    def _move_up(self) -> None:
        row = self._current_row
        if row <= 0 or row >= self._list.count():
            return
        orig_a = self._list.item(row).data(Qt.ItemDataRole.UserRole)
        orig_b = self._list.item(row - 1).data(Qt.ItemDataRole.UserRole)
        self._mgr.move_block(self._field_key, orig_a, orig_b)
        self._blocks = self._mgr.get_blocks(self._field_key)
        self._refresh_list(selected_row=row - 1)

    def _move_down(self) -> None:
        row = self._current_row
        if row < 0 or row >= self._list.count() - 1:
            return
        orig_a = self._list.item(row).data(Qt.ItemDataRole.UserRole)
        orig_b = self._list.item(row + 1).data(Qt.ItemDataRole.UserRole)
        self._mgr.move_block(self._field_key, orig_a, orig_b)
        self._blocks = self._mgr.get_blocks(self._field_key)
        self._refresh_list(selected_row=row + 1)

    def _update_status(self) -> None:
        n = sum(
            1 for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        )
        self._status_lbl.setText(f"{n} block{'s' if n != 1 else ''} selected for this run")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def selected_texts(self) -> list[str]:
        """Return checked block texts in current list order."""
        result: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                orig_idx = item.data(Qt.ItemDataRole.UserRole)
                if orig_idx < len(self._blocks):
                    result.append(self._blocks[orig_idx])
        return result


# ---------------------------------------------------------------------------
# Text section widget (single QTextEdit  OR  multi-text picker button)
# ---------------------------------------------------------------------------

class TextSection(QWidget):
    """Replaces bare QTextEdit for any string input.

    Single mode (default) — behaves exactly like the normal text edit.
    Multi-text mode        — shows a picker button; each selected text block
                             triggers a separate generation (Cartesian with LoRA).
    """

    def __init__(
        self,
        field_key: str,
        initial_text: str,
        text_mgr: TextBlockManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._field_key = field_key
        self._text_mgr = text_mgr
        self._selected_texts: list[str] = []
        self._build_ui(initial_text)

    def _build_ui(self, initial_text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(4)

        # Multi-text toggle checkbox
        self._multi_cb = QCheckBox("Multi-Text Mode", self)
        self._multi_cb.setToolTip(
            "Enable to select multiple text blocks and run one generation per block."
        )
        self._multi_cb.setStyleSheet("font-size: 11px; color: #8ab4d4;")
        self._multi_cb.toggled.connect(self._on_mode_toggled)
        layout.addWidget(self._multi_cb)

        # Single mode: text edit
        self._editor = QTextEdit(self)
        self._editor.setPlainText(initial_text)
        self._editor.setFixedHeight(72)
        self._editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._editor)

        # Multi mode: picker button (hidden initially)
        self._picker_btn = QPushButton(self._picker_label(), self)
        self._picker_btn.setVisible(False)
        self._picker_btn.clicked.connect(self._open_picker)
        layout.addWidget(self._picker_btn)

    # ------------------------------------------------------------------
    # Mode toggle
    # ------------------------------------------------------------------

    def _on_mode_toggled(self, checked: bool) -> None:
        self._editor.setVisible(not checked)
        self._picker_btn.setVisible(checked)
        if checked:
            # Promote current editor text into library if non-empty and unique
            current = self._editor.toPlainText().strip()
            if current:
                idx = self._text_mgr.add_block_if_new(self._field_key, current)
                # Pre-select it if it was new or is the only selection so far
                if not self._selected_texts:
                    self._selected_texts = [current]
        self._picker_btn.setText(self._picker_label())

    # ------------------------------------------------------------------
    # Picker dialog
    # ------------------------------------------------------------------

    def _open_picker(self) -> None:
        dlg = TextPickerDialog(
            self._field_key, self._text_mgr, self._selected_texts, self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._selected_texts = dlg.selected_texts
            self._picker_btn.setText(self._picker_label())

    def _picker_label(self) -> str:
        n = len(self._selected_texts)
        if n == 0:
            return "Select text blocks…"
        return f"\U0001f4dd {n} block{'s' if n != 1 else ''} selected — click to change"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_multi_mode(self) -> bool:
        return self._multi_cb.isChecked()

    def get_value(self) -> str:
        """Return single text — single mode text or first selected block."""
        if self._multi_cb.isChecked():
            return self._selected_texts[0] if self._selected_texts else ""
        return self._editor.toPlainText()

    def get_multi_texts(self) -> list[str] | None:
        """Multi mode → ordered selection; single mode → None."""
        if self._multi_cb.isChecked():
            return list(self._selected_texts)
        return None

    def set_single_value(self, text: str) -> None:
        """Restore single-mode text (used by apply_overrides)."""
        self._editor.setPlainText(text)

    def set_multi_state(self, enabled: bool, selected: list[str]) -> None:
        """Restore multi-mode state (used by apply_overrides)."""
        self._selected_texts = list(selected)
        if enabled and not self._multi_cb.isChecked():
            self._multi_cb.setChecked(True)   # triggers _on_mode_toggled
        elif not enabled and self._multi_cb.isChecked():
            self._multi_cb.setChecked(False)
        self._picker_btn.setText(self._picker_label())


# ---------------------------------------------------------------------------
# Dimension size picker dialog
# ---------------------------------------------------------------------------

class DimPickerDialog(QDialog):
    """Dialog for managing a list of W×H size pairs for multi-dimension mode."""

    def __init__(
        self,
        divisor: int,
        pairs: list[tuple[int, int]],
        width_name: str = "width",
        height_name: str = "height",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Sizes")
        self.setMinimumSize(320, 360)
        self._divisor = divisor
        self._width_name = width_name
        self._height_name = height_name
        # Work on a mutable copy; each entry is [w, h]
        self._pairs: list[list[int]] = [list(p) for p in pairs]
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hint = QLabel(
            f"Each row is one W\u00d7H size. Values snap to multiples of {self._divisor}.",
            self,
        )
        hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list, stretch=1)

        # Inline editor row (shown below list)
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("W:", self))
        self._w_spin = QSpinBox(self)
        self._w_spin.setRange(self._divisor, 16384)
        self._w_spin.setSingleStep(self._divisor)
        self._w_spin.editingFinished.connect(self._snap_and_sync)
        edit_row.addWidget(self._w_spin)
        edit_row.addWidget(QLabel("H:", self))
        self._h_spin = QSpinBox(self)
        self._h_spin.setRange(self._divisor, 16384)
        self._h_spin.setSingleStep(self._divisor)
        self._h_spin.editingFinished.connect(self._snap_and_sync)
        edit_row.addWidget(self._h_spin)
        self._apply_btn = QPushButton("Apply", self)
        self._apply_btn.setFixedHeight(24)
        self._apply_btn.clicked.connect(self._apply_edit)
        edit_row.addWidget(self._apply_btn)
        layout.addLayout(edit_row)

        # Add / remove row
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add", self)
        add_btn.setFixedHeight(24)
        add_btn.clicked.connect(self._add_pair)
        del_btn = QPushButton("Remove", self)
        del_btn.setFixedHeight(24)
        del_btn.clicked.connect(self._remove_pair)
        dup_btn = QPushButton("Duplicate", self)
        dup_btn.setFixedHeight(24)
        dup_btn.clicked.connect(self._duplicate_pair)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(dup_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_list()

    def _label(self, w: int, h: int) -> str:
        return f"{w} \u00d7 {h}"

    def _refresh_list(self, select_row: int = -1) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for w, h in self._pairs:
            self._list.addItem(self._label(w, h))
        self._list.blockSignals(False)
        row = select_row if 0 <= select_row < len(self._pairs) else (len(self._pairs) - 1)
        self._list.setCurrentRow(row)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._pairs):
            self._w_spin.setValue(self._pairs[row][0])
            self._h_spin.setValue(self._pairs[row][1])

    def _snap(self, v: int) -> int:
        d = self._divisor
        return max(d, round(v / d) * d)

    def _snap_and_sync(self) -> None:
        """Snap both spinboxes on editingFinished, don't commit to list yet."""
        self._w_spin.setValue(self._snap(self._w_spin.value()))
        self._h_spin.setValue(self._snap(self._h_spin.value()))

    def _apply_edit(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._pairs):
            w = self._snap(self._w_spin.value())
            h = self._snap(self._h_spin.value())
            self._pairs[row] = [w, h]
            self._list.item(row).setText(self._label(w, h))

    def _add_pair(self) -> None:
        d = self._divisor
        # Default to last entry, or 512×512 if list is empty
        if self._pairs:
            w, h = self._pairs[-1]
        else:
            w = h = max(d, self._snap(512))
        self._pairs.append([w, h])
        self._refresh_list(len(self._pairs) - 1)

    def _remove_pair(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._pairs) and len(self._pairs) > 1:
            self._pairs.pop(row)
            self._refresh_list(min(row, len(self._pairs) - 1))

    def _duplicate_pair(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._pairs):
            self._pairs.insert(row + 1, list(self._pairs[row]))
            self._refresh_list(row + 1)

    @property
    def pairs(self) -> list[tuple[int, int]]:
        """Return the final list of (w, h) tuples."""
        return [(p[0], p[1]) for p in self._pairs]


# ---------------------------------------------------------------------------
# Dimension section widget (spinboxes  OR  multi-dim picker button)
# ---------------------------------------------------------------------------

class DimSection(QWidget):
    """Wraps the width + height spinboxes for a node.

    Single mode (default) — two plain spinboxes, identical to before.
    Multi-Dim mode         — shows a button that opens DimPickerDialog; each
                             (W, H) pair triggers a separate generation.
    """

    def __init__(
        self,
        width_name: str,
        height_name: str,
        width_val: int,
        height_val: int,
        divisor: int,
        has_batch_size: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._width_name = width_name
        self._height_name = height_name
        self._divisor = divisor
        self._has_batch_size = has_batch_size
        self._pairs: list[tuple[int, int]] = [(width_val, height_val)]
        self._build_ui(width_val, height_val)

    def _build_ui(self, width_val: int, height_val: int) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(4)

        self._multi_cb = QCheckBox("Multi-Dim Mode", self)
        self._multi_cb.setToolTip(
            "Enable to specify multiple W\u00d7H sizes and run one generation per size."
        )
        self._multi_cb.setStyleSheet("font-size: 11px; color: #8ab4d4;")
        self._multi_cb.toggled.connect(self._on_mode_toggled)
        layout.addWidget(self._multi_cb)

        # Single-mode spinboxes (side by side)
        spin_row = QHBoxLayout()
        spin_row.setContentsMargins(0, 0, 0, 0)
        spin_row.setSpacing(4)
        spin_row.addWidget(QLabel(f"{self._width_name}:", self))
        self._w_spin = self._make_spin(width_val)
        spin_row.addWidget(self._w_spin)
        spin_row.addWidget(QLabel(f"{self._height_name}:", self))
        self._h_spin = self._make_spin(height_val)
        spin_row.addWidget(self._h_spin)
        self._spin_container = QWidget(self)
        self._spin_container.setLayout(spin_row)
        layout.addWidget(self._spin_container)

        # Multi-mode picker button (hidden initially)
        self._picker_btn = QPushButton(self._picker_label(), self)
        self._picker_btn.setVisible(False)
        self._picker_btn.clicked.connect(self._open_picker)
        layout.addWidget(self._picker_btn)

    def _make_spin(self, value: int) -> QSpinBox:
        d = self._divisor
        snapped = max(d, round(value / d) * d)
        w = QSpinBox(self)
        w.setRange(d, 16384)
        w.setSingleStep(d)
        w.setValue(snapped)
        w.setToolTip(
            f"Must be a multiple of {d}. "
            "Values are automatically rounded to the nearest valid multiple."
        )
        def _snap() -> None:
            v = w.value()
            n = max(d, round(v / d) * d)
            if n != v:
                w.setValue(n)
        w.editingFinished.connect(_snap)
        return w

    def _on_mode_toggled(self, checked: bool) -> None:
        self._spin_container.setVisible(not checked)
        self._picker_btn.setVisible(checked)
        if checked and not self._pairs:
            self._pairs = [(self._w_spin.value(), self._h_spin.value())]
        elif checked:
            # Keep first pair in sync with current spinbox values
            self._pairs[0] = (self._w_spin.value(), self._h_spin.value())
        self._picker_btn.setText(self._picker_label())

    def _open_picker(self) -> None:
        dlg = DimPickerDialog(
            self._divisor, self._pairs,
            self._width_name, self._height_name, self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._pairs = dlg.pairs
            self._picker_btn.setText(self._picker_label())

    def _picker_label(self) -> str:
        n = len(self._pairs)
        if n == 0:
            return "Edit sizes\u2026"
        suffix = " (batch\u2192forced 1)" if self._has_batch_size else ""
        return f"\U0001f4d0 {n} size{'s' if n != 1 else ''} \u2014 click to change{suffix}"

    # ------------------------------------------------------------------
    # Public API (mirrors LoRASection / TextSection patterns)
    # ------------------------------------------------------------------

    def is_multi_mode(self) -> bool:
        return self._multi_cb.isChecked()

    def get_width(self) -> int:
        return self._w_spin.value()

    def get_height(self) -> int:
        return self._h_spin.value()

    def get_pairs(self) -> list[tuple[int, int]] | None:
        """Multi mode → list of (w, h); single mode → None."""
        if self._multi_cb.isChecked():
            return list(self._pairs)
        return None

    def set_values(self, width: int, height: int) -> None:
        """Restore single-mode spinbox values (used by apply_overrides)."""
        self._w_spin.setValue(width)
        self._h_spin.setValue(height)

    def set_multi_state(self, enabled: bool, pairs: list[tuple[int, int]]) -> None:
        """Restore multi-mode state (used by apply_overrides)."""
        if pairs:
            self._pairs = list(pairs)
        if enabled and not self._multi_cb.isChecked():
            self._multi_cb.setChecked(True)
        elif not enabled and self._multi_cb.isChecked():
            self._multi_cb.setChecked(False)
        self._picker_btn.setText(self._picker_label())


# ---------------------------------------------------------------------------
# Per-node editable form
# ---------------------------------------------------------------------------

class _NodeForm(QGroupBox):
    """Dynamic form for a single editable workflow node."""

    # Input names treated as spatial dimensions and subject to divisor snapping.
    _DIM_INPUTS = {"width", "height", "max_width", "max_height",
                   "image_width", "image_height", "target_width", "target_height"}

    # Paired width → height names.  When a node has both, a single DimSection
    # is rendered instead of two independent spinboxes.
    _DIM_PAIRS: dict[str, str] = {
        "width":        "height",
        "max_width":    "max_height",
        "image_width":  "image_height",
        "target_width": "target_height",
    }

    # Input names rendered as multi-line text areas (TextSection).
    _TEXT_AREA_INPUTS = {"text", "text_g", "text_l", "text_positive", "text_negative",
                         "positive", "negative", "caption", "prompt", "description"}

    def __init__(
        self,
        node: EditableNode,
        options: dict[str, list[str]],
        dimension_divisor: int = 64,
        parent: QWidget | None = None,
        text_mgr: TextBlockManager | None = None,
    ) -> None:
        super().__init__(f"{node.title}  [{node.node_id}]", parent)
        self._node = node
        self._options = options  # input_name -> list of choices from server
        self._dimension_divisor = dimension_divisor
        self._text_mgr = text_mgr
        self._widgets: dict[str, QWidget] = {}
        self._seed_randomize: dict[str, QCheckBox] = {}
        self._build()

    def _build(self) -> None:
        self.setCheckable(True)
        self.setChecked(True)
        self.setToolTip(
            "Uncheck to bypass this node — it will use its original workflow values "
            "and be excluded from generation."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)

        inputs = self._node.inputs
        has_batch = "batch_size" in inputs

        # Height-like names that are already covered by a paired DimSection — skip
        # their standalone row so they only appear inside the DimSection widget.
        _height_skip: set[str] = set()
        for w_name, h_name in self._DIM_PAIRS.items():
            if (
                w_name in inputs and h_name in inputs
                and isinstance(inputs[w_name], int)
                and isinstance(inputs[h_name], int)
            ):
                _height_skip.add(h_name)

        for input_name, value in inputs.items():
            if input_name in _height_skip:
                continue  # rendered inside DimSection for its paired width

            row = QHBoxLayout()

            # Check whether this is the width side of a dimension pair
            h_name = self._DIM_PAIRS.get(input_name)
            if (
                h_name and h_name in inputs
                and isinstance(value, int)
                and isinstance(inputs[h_name], int)
            ):
                lbl = QLabel(f"{input_name}/{h_name}:", self)
                lbl.setFixedWidth(110)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(lbl)
                dim_section = DimSection(
                    width_name=input_name,
                    height_name=h_name,
                    width_val=value,
                    height_val=inputs[h_name],
                    divisor=self._dimension_divisor,
                    has_batch_size=has_batch,
                    parent=self,
                )
                row.addWidget(dim_section)
                # Register under width_name; get_overrides reads height from it too
                self._widgets[input_name] = dim_section
                layout.addLayout(row)
                continue

            lbl = QLabel(input_name + ":", self)
            lbl.setFixedWidth(110)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(lbl)

            widget = self._make_widget(input_name, value)
            row.addWidget(widget)
            self._widgets[input_name] = widget

            # Seed gets a randomize checkbox
            if input_name == "seed":
                cb = QCheckBox("rand", self)
                cb.setToolTip("Randomize seed on each generation")
                cb.toggled.connect(lambda checked, w=widget: w.setEnabled(not checked))
                self._seed_randomize[input_name] = cb
                row.addWidget(cb)

            layout.addLayout(row)

    def _make_widget(self, name: str, value: Any) -> QWidget:
        # --- Server-supplied option list → searchable QComboBox (or LoRASection) ---
        choices = self._options.get(name, [])
        if choices:
            if name == "lora_name":
                return LoRASection(choices, str(value), self)
            return self._make_combo(name, choices, str(value))

        if isinstance(value, bool):
            w = QCheckBox(self)
            w.setChecked(value)
            return w
        if isinstance(value, int):
            # Standalone dimension input (unpaired — e.g. only width is present, no height)
            if name in self._DIM_INPUTS:
                return self._make_dimension_spinbox(name, value)
            w = QSpinBox(self)
            w.setRange(-2_147_483_648, 2_147_483_647)
            if name in ("seed",):
                w.setRange(0, 2_147_483_647)  # QSpinBox is signed 32-bit
            w.setValue(min(value, 2_147_483_647))
            return w
        if isinstance(value, float):
            w = QDoubleSpinBox(self)
            w.setRange(0.0, 100.0)
            w.setSingleStep(0.1)
            w.setDecimals(3)
            w.setValue(value)
            return w
        # String — use TextSection for text-area inputs, QLineEdit for others
        if isinstance(value, str):
            if name in self._TEXT_AREA_INPUTS and self._text_mgr is not None:
                field_key = f"{self._node.title}_{name}"
                return TextSection(field_key, str(value), self._text_mgr, self)
            w = QLineEdit(self)
            w.setText(str(value))
            return w
        w = QLineEdit(self)
        w.setText(str(value))
        return w

    def _make_dimension_spinbox(self, name: str, value: int) -> QSpinBox:
        """Build a QSpinBox that snaps to the nearest multiple of dimension_divisor."""
        d = self._dimension_divisor
        snapped = max(d, round(value / d) * d)
        w = QSpinBox(self)
        w.setRange(d, 16384)
        w.setSingleStep(d)
        w.setValue(snapped)
        w.setToolTip(
            f"Must be a multiple of {d}. "
            "Values are automatically rounded to the nearest valid multiple."
        )

        def _snap() -> None:
            val = w.value()
            nearest = max(d, round(val / d) * d)
            if nearest != val:
                w.setValue(nearest)

        w.editingFinished.connect(_snap)
        return w

    def _make_combo(self, name: str, choices: list[str], current: str) -> QComboBox:
        """Build an editable, searchable QComboBox populated with server choices."""
        combo = QComboBox(self)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItems(choices)
        # Pre-select the value that was in the workflow, if present
        idx = combo.findText(current, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentText(current)
        # Attach a case-insensitive substring completer
        completer = QCompleter(choices, combo)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        combo.setCompleter(completer)
        folder = _INPUT_TO_FOLDER.get(name, "")
        tip = f"{len(choices)} options"
        if folder:
            tip += f" (from models/{folder})"
        combo.setToolTip(tip)
        return combo

    def is_bypassed(self) -> bool:
        """Return True when the node's group box checkbox is unchecked."""
        return not self.isChecked()

    def get_overrides(self, for_generate: bool = True) -> dict[str, Any]:
        """Collect current widget values as an input override dict.

        When *for_generate* is True (default, used at generation time), a checked
        rand checkbox substitutes a fresh random seed.  When False (used when
        snapshotting for persistence), the spinbox's actual displayed value is used
        so the saved state isn't polluted with throwaway random numbers.

        Bypassed nodes (group box unchecked) return an empty dict at generation
        time so their original workflow values are used unchanged.
        """
        # Bypassed: omit from generation but still snapshot all values for persistence
        if for_generate and self.is_bypassed():
            return {}

        result: dict[str, Any] = {}
        for name, widget in self._widgets.items():
            # Check if seed is marked random — only substitute when actually generating
            if for_generate and name in self._seed_randomize and self._seed_randomize[name].isChecked():
                result[name] = random.randint(0, 2_147_483_647)
                continue
            if isinstance(widget, QCheckBox):
                result[name] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                result[name] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                result[name] = widget.value()
            elif isinstance(widget, QTextEdit):
                result[name] = widget.toPlainText()
            elif isinstance(widget, QLineEdit):
                result[name] = widget.text()
            elif isinstance(widget, QComboBox):
                result[name] = widget.currentText()
            elif isinstance(widget, LoRASection):
                result[name] = widget.get_value()  # always a single str
            elif isinstance(widget, TextSection):
                result[name] = widget.get_value()  # always a single str
            elif isinstance(widget, DimSection):
                # Emit both width (name) and height from the single DimSection
                result[name] = widget.get_width()
                result[widget._height_name] = widget.get_height()
        # When snapshotting for persistence, save rand checkbox state too
        if not for_generate:
            for seed_name, cb in self._seed_randomize.items():
                result[f"__rand_{seed_name}__"] = cb.isChecked()
            # Save TextSection multi-mode state
            for name, widget in self._widgets.items():
                if isinstance(widget, TextSection) and widget.is_multi_mode():
                    texts = widget.get_multi_texts() or []
                    result[f"__text_multi_{name}__"] = True
                    result[f"__text_sel_{name}__"] = texts
            # Save DimSection multi-mode state
            for name, widget in self._widgets.items():
                if isinstance(widget, DimSection) and widget.is_multi_mode():
                    pairs = widget.get_pairs() or []
                    result[f"__dim_multi_{name}__"] = True
                    result[f"__dim_pairs_{name}__"] = [list(p) for p in pairs]
            # Save bypass state
            result["__bypassed__"] = self.is_bypassed()
        return result

    def apply_overrides(self, data: dict) -> None:
        """Restore saved widget values from a {input_name: value} dict."""
        # Restore bypass state before anything else (affects child widget enabled state)
        if "__bypassed__" in data:
            self.setChecked(not bool(data["__bypassed__"]))
        # Restore rand checkbox states first (they affect spinbox enabled state)
        for key, value in data.items():
            if key.startswith("__rand_") and key.endswith("__"):
                input_name = key[7:-2]  # strip __rand_ prefix and __ suffix
                cb = self._seed_randomize.get(input_name)
                if cb:
                    cb.setChecked(bool(value))
        # Restore TextSection multi-mode state (do before widget value pass)
        for key, value in data.items():
            if key.startswith("__text_multi_") and key.endswith("__"):
                input_name = key[13:-2]
                if bool(value):
                    sel_key = f"__text_sel_{input_name}__"
                    selected = data.get(sel_key, [])
                    widget = self._widgets.get(input_name)
                    if isinstance(widget, TextSection):
                        widget.set_multi_state(True, selected if isinstance(selected, list) else [])
        # Restore DimSection multi-mode state (do before widget value pass)
        for key, value in data.items():
            if key.startswith("__dim_multi_") and key.endswith("__"):
                width_name = key[12:-2]
                if bool(value):
                    pairs_key = f"__dim_pairs_{width_name}__"
                    raw = data.get(pairs_key, [])
                    pairs = [tuple(p) for p in raw if isinstance(p, (list, tuple)) and len(p) == 2]
                    widget = self._widgets.get(width_name)
                    if isinstance(widget, DimSection):
                        widget.set_multi_state(True, pairs)
        for name, value in data.items():
            if name.startswith("__"):
                continue  # skip meta keys
            widget = self._widgets.get(name)
            if widget is None:
                continue
            try:
                if isinstance(widget, LoRASection):
                    widget.set_single_value(str(value))
                elif isinstance(widget, TextSection):
                    widget.set_single_value(str(value))
                elif isinstance(widget, DimSection):
                    # DimSection is stored under width_name; fetch height from data
                    h_val = data.get(widget._height_name, widget.get_height())
                    widget.set_values(int(value), int(h_val))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QSpinBox):
                    widget.setValue(int(value))
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setValue(float(value))
                elif isinstance(widget, QTextEdit):
                    widget.setPlainText(str(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(str(value))
            except Exception:
                pass  # silently skip type-mismatch

    def get_multi_dims(self) -> list[tuple[str, list[dict]]]:
        """Return all active multi-mode dimensions from this form.

        Each entry is ``(label, steps)`` where *steps* is a list of node-patch
        dicts ``{node_id: {input_name: value}}``.  Empty list when no multi-mode
        dimensions are active.
        """
        if self.is_bypassed():
            return []

        dims: list[tuple[str, list[dict]]] = []
        node_id = self._node.node_id
        node_title = self._node.title

        # LoRA dimension
        lora_w = self._widgets.get("lora_name")
        if isinstance(lora_w, LoRASection) and lora_w.is_multi_mode():
            selections = lora_w.get_multi_selection() or []
            if selections:
                steps = [{node_id: {"lora_name": lora}} for lora in selections]
                dims.append((f"{node_title}: LoRA", steps))

        # Text dimensions (one per TextSection in multi mode)
        for input_name, widget in self._widgets.items():
            if isinstance(widget, TextSection) and widget.is_multi_mode():
                texts = widget.get_multi_texts() or []
                if texts:
                    steps = [{node_id: {input_name: text}} for text in texts]
                    dims.append((f"{node_title}: {input_name}", steps))

        # Dimension pairs (one step per W×H pair)
        for input_name, widget in self._widgets.items():
            if isinstance(widget, DimSection) and widget.is_multi_mode():
                pairs = widget.get_pairs() or []
                if pairs:
                    steps: list[dict] = []
                    for w_val, h_val in pairs:
                        patch: dict[str, Any] = {
                            input_name: w_val,
                            widget._height_name: h_val,
                        }
                        if widget._has_batch_size:
                            patch["batch_size"] = 1
                        steps.append({node_id: patch})
                    dims.append((f"{node_title}: {input_name}×{widget._height_name}", steps))

        return dims


class WorkflowPanel(QWidget):
    """Load a workflow JSON file and render editable node forms."""

    generate_requested = Signal(dict, str, int, list)  # overrides, workflow_path, batch_count, dims
    refresh_models_requested = Signal()                  # user clicked ⟳ refresh button
    stop_current_requested   = Signal()                  # interrupt running job
    clear_queue_requested    = Signal()                  # delete pending jobs only
    stop_and_clear_requested = Signal()                  # interrupt + clear all
    retry_last_requested     = Signal()                  # re-submit last job

    def __init__(
        self,
        cfg_mgr: ConfigManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg_mgr = cfg_mgr
        self._manager = WorkflowManager()
        self._text_mgr = TextBlockManager()
        self._node_forms: list[_NodeForm] = []
        self._is_connected = False
        self._server_options: dict[str, list[str]] = {}  # input_name -> [choices]
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # --- Checklist banner ---
        self._checklist = QFrame(self)
        self._checklist.setFrameShape(QFrame.Shape.StyledPanel)
        self._checklist.setStyleSheet(
            "QFrame { background: #1e2a38; border: 1px solid #2d4a6a; border-radius: 4px; padding: 2px; }"
        )
        checklist_layout = QVBoxLayout(self._checklist)
        checklist_layout.setContentsMargins(8, 6, 8, 6)
        checklist_layout.setSpacing(3)

        title = QLabel("Getting started:", self._checklist)
        title.setStyleSheet("color: #8ab4d4; font-weight: bold; font-size: 11px; border: none;")
        checklist_layout.addWidget(title)

        self._check_connect = QLabel("  ✗  Connect to a ComfyUI server above", self._checklist)
        self._check_connect.setStyleSheet("color: #e06c6c; font-size: 11px; border: none;")
        checklist_layout.addWidget(self._check_connect)

        self._check_workflow = QLabel("  ✗  Load a workflow JSON file (API format)", self._checklist)
        self._check_workflow.setStyleSheet("color: #e06c6c; font-size: 11px; border: none;")
        checklist_layout.addWidget(self._check_workflow)

        self._check_hint = QLabel(
            "  ℹ  In ComfyUI: Settings → Enable Dev Mode, then\n"
            "      use \"Save (API Format)\" from the workflow menu.",
            self._checklist
        )
        self._check_hint.setStyleSheet("color: #888; font-size: 10px; border: none;")
        checklist_layout.addWidget(self._check_hint)

        root.addWidget(self._checklist)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        self._load_btn = QPushButton("Load Workflow…", self)
        self._load_btn.clicked.connect(self._on_load)
        self._load_img_btn = QPushButton("From Image…", self)
        self._load_img_btn.setToolTip("Extract workflow embedded in a ComfyUI-generated PNG")
        self._load_img_btn.clicked.connect(self._on_load_from_image)
        self._workflow_label = QLabel("No workflow loaded", self)
        self._workflow_label.setStyleSheet("color: #888; font-size: 11px;")
        self._workflow_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._refresh_btn = QPushButton("⟳", self)
        self._refresh_btn.setFixedWidth(28)
        self._refresh_btn.setToolTip("Refresh model/LoRA lists from server")
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self.refresh_models_requested.emit)
        toolbar.addWidget(self._load_btn)
        toolbar.addWidget(self._load_img_btn)
        toolbar.addWidget(self._workflow_label)
        toolbar.addWidget(self._refresh_btn)
        root.addLayout(toolbar)

        # --- Scrollable node forms area ---
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._forms_container = QWidget()
        self._forms_layout = QVBoxLayout(self._forms_container)
        self._forms_layout.setContentsMargins(4, 4, 4, 4)
        self._forms_layout.setSpacing(8)

        # Placeholder shown when no workflow is loaded
        self._placeholder = QLabel(
            "Load a workflow JSON to see editable parameters here.",
            self._forms_container
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #555; font-size: 12px; padding: 24px;")
        self._placeholder.setWordWrap(True)
        self._forms_layout.addWidget(self._placeholder)
        self._forms_layout.addStretch(1)

        self._scroll.setWidget(self._forms_container)
        root.addWidget(self._scroll, stretch=1)

        # --- Batch size + Generate row ---
        gen_row = QHBoxLayout()
        gen_row.setSpacing(6)

        batch_lbl = QLabel("Batch:", self)
        batch_lbl.setToolTip("Number of times to submit the workflow (each run gets a fresh seed)")
        self._batch_spin = QSpinBox(self)
        self._batch_spin.setRange(1, 100)
        self._batch_spin.setValue(1)
        self._batch_spin.setFixedWidth(56)
        self._batch_spin.setToolTip("Number of images to generate")

        self._generate_btn = QPushButton("Generate", self)
        self._generate_btn.setEnabled(False)
        self._generate_btn.setFixedHeight(36)
        self._generate_btn.setStyleSheet(
            "QPushButton { background-color: #2b6cb0; color: white; font-weight: bold; border-radius: 4px; }"
            "QPushButton:disabled { background-color: #444; color: #888; }"
            "QPushButton:hover { background-color: #3182ce; }"
        )
        self._generate_btn.setToolTip("Connect to ComfyUI and load a workflow to enable")
        self._generate_btn.clicked.connect(self._on_generate)
        self._generate_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        gen_row.addWidget(batch_lbl)
        gen_row.addWidget(self._batch_spin)
        gen_row.addWidget(self._generate_btn)
        root.addLayout(gen_row)

        # --- Control buttons row ---
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(4)

        self._stop_btn = QPushButton("Stop", self)
        self._stop_btn.setFixedHeight(28)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setToolTip("Interrupt the currently running generation immediately")
        self._stop_btn.setStyleSheet(
            "QPushButton { background-color: #8b1a1a; color: white; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #c0392b; }"
            "QPushButton:disabled { background-color: #444; color: #666; }"
        )
        self._stop_btn.clicked.connect(self.stop_current_requested)

        self._clear_queue_btn = QPushButton("Clear Queue", self)
        self._clear_queue_btn.setFixedHeight(28)
        self._clear_queue_btn.setEnabled(False)
        self._clear_queue_btn.setToolTip("Remove all pending jobs from the queue (running job continues)")
        self._clear_queue_btn.setStyleSheet(
            "QPushButton { background-color: #7a4a00; color: white; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #b36b00; }"
            "QPushButton:disabled { background-color: #444; color: #666; }"
        )
        self._clear_queue_btn.clicked.connect(self.clear_queue_requested)

        self._stop_clear_btn = QPushButton("Stop + Clear", self)
        self._stop_clear_btn.setFixedHeight(28)
        self._stop_clear_btn.setEnabled(False)
        self._stop_clear_btn.setToolTip("Interrupt current job AND clear all pending jobs")
        self._stop_clear_btn.setStyleSheet(
            "QPushButton { background-color: #5c1111; color: #ffaaaa; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #8b1a1a; color: white; }"
            "QPushButton:disabled { background-color: #444; color: #666; }"
        )
        self._stop_clear_btn.clicked.connect(self.stop_and_clear_requested)

        self._retry_btn = QPushButton("↺ Retry", self)
        self._retry_btn.setFixedHeight(28)
        self._retry_btn.setEnabled(False)
        self._retry_btn.setToolTip("Re-submit the last completed or failed job with the same settings")
        self._retry_btn.setStyleSheet(
            "QPushButton { background-color: #2a4a2a; color: #aaddaa; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background-color: #3a7a3a; color: white; }"
            "QPushButton:disabled { background-color: #444; color: #666; }"
        )
        self._retry_btn.clicked.connect(self.retry_last_requested)

        ctrl_row.addWidget(self._stop_btn)
        ctrl_row.addWidget(self._clear_queue_btn)
        ctrl_row.addWidget(self._stop_clear_btn)
        ctrl_row.addWidget(self._retry_btn)
        root.addLayout(ctrl_row)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_load(self) -> None:
        start_dir = ""
        if self._cfg_mgr:
            start_dir = self._cfg_mgr.config.last_workflow_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Workflow", start_dir, "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            self._manager.load_from_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Workflow Error", str(exc))
            return
        # Persist the directory and path for next session
        if self._cfg_mgr:
            import os as _os
            self._cfg_mgr.update(
                last_workflow_dir=_os.path.dirname(path),
                last_workflow_path=path,
            )
        self._populate_forms()

    def _on_load_from_image(self) -> None:
        start_dir = ""
        if self._cfg_mgr:
            start_dir = self._cfg_mgr.config.last_workflow_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PNG Image", start_dir,
            "PNG Images (*.png);;All Files (*)"
        )
        if not path:
            return
        try:
            self._manager.load_from_png(path)
        except Exception as exc:
            QMessageBox.critical(self, "Workflow Error", str(exc))
            return
        if self._cfg_mgr:
            import os as _os
            self._cfg_mgr.update(
                last_workflow_dir=_os.path.dirname(path),
                last_workflow_path=path,
            )
        self._populate_forms()

    def load_from_path(self, path: str) -> bool:
        """Silently load a workflow from *path*. Returns True on success.

        Accepts both ``.json`` API-format files and ``.png`` files with
        embedded workflow metadata.  Used by MainWindow on startup to restore
        the previous session's workflow.  Also restores last-session form
        values and batch count from config.
        """
        try:
            if path.lower().endswith(".png"):
                self._manager.load_from_png(path)
            else:
                self._manager.load_from_file(path)
        except Exception:
            return False
        self._populate_forms()
        # Restore last-session input values
        if self._cfg_mgr:
            saved = self._cfg_mgr.config.workflow_overrides
            if saved:
                for form in self._node_forms:
                    node_data = saved.get(form._node.node_id)
                    if node_data and isinstance(node_data, dict):
                        form.apply_overrides(node_data)
            self._batch_spin.setValue(self._cfg_mgr.config.batch_count)
        return True

    def load_from_png_bytes(self, raw: bytes) -> bool:
        """Extract and load a workflow from in-memory PNG bytes.

        Returns True on success, False on failure.  Call-sites that need to
        show error dialogs should check the return value and display their
        own message.
        """
        try:
            self._manager.load_from_png_bytes(raw)
        except Exception:
            return False
        self._populate_forms()
        return True

    def get_all_overrides(self) -> dict:
        """Return {node_id: {input_name: value}} for all current form widgets."""
        return {
            form._node.node_id: form.get_overrides(for_generate=False)
            for form in self._node_forms
        }

    def get_batch_count(self) -> int:
        return self._batch_spin.value()

    def _on_generate(self) -> None:
        from ui.multi_dim_order_dialog import MultiDimOrderDialog

        overrides: dict[str, dict] = {}
        dims: list[tuple[str, list[dict]]] = []

        for form in self._node_forms:
            overrides[form._node.node_id] = form.get_overrides()
            dims.extend(form.get_multi_dims())

        # If 2+ multi-dimensions are active, let the user set loop order
        if len(dims) >= 2:
            dlg = MultiDimOrderDialog(dims, self._batch_spin.value(), self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            dims = dlg.ordered_dims()

        # Emit just the ordered dims list (MainWindow builds the Cartesian product)
        self.generate_requested.emit(
            overrides, self._manager.path, self._batch_spin.value(),
            [steps for _, steps in dims],   # strip labels, keep ordered steps lists
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _populate_forms(self) -> None:
        # Clear old forms (everything before the stretch)
        self._node_forms.clear()
        while self._forms_layout.count() > 0:
            item = self._forms_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        nodes = self._manager.get_editable_nodes()

        if not nodes:
            msg = QLabel(
                "Workflow loaded, but no recognisable editable nodes were found.\n\n"
                "Make sure you exported using \"Save (API Format)\" from ComfyUI.\n"
                "Standard workflow exports are not supported.",
                self._forms_container
            )
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet("color: #c0a060; font-size: 11px; padding: 16px;")
            msg.setWordWrap(True)
            self._forms_layout.addWidget(msg)
        else:
            for node in nodes:
                # Build per-node option dict: prefer node-class-specific options
                # where the server gave us choices for this input name
                divisor = self._cfg_mgr.config.dimension_divisor if self._cfg_mgr else 64
                form = _NodeForm(
                    node, self._server_options, divisor, self._forms_container,
                    text_mgr=self._text_mgr,
                )
                self._node_forms.append(form)
                self._forms_layout.addWidget(form)

        self._forms_layout.addStretch(1)

        name = self._manager.path.split("/")[-1].split("\\")[-1]
        node_count = len(nodes)
        self._workflow_label.setText(
            f"{name}  ({node_count} editable node{'s' if node_count != 1 else ''})"
        )
        self._update_checklist()
        self._refresh_generate_btn()

    def _update_checklist(self) -> None:
        """Refresh the checklist banner state."""
        if self._is_connected:
            self._check_connect.setText("  ✓  Connected to ComfyUI server")
            self._check_connect.setStyleSheet("color: #6ec46e; font-size: 11px; border: none;")
        else:
            self._check_connect.setText("  ✗  Connect to a ComfyUI server above")
            self._check_connect.setStyleSheet("color: #e06c6c; font-size: 11px; border: none;")

        if self._manager.is_loaded:
            name = self._manager.path.split("/")[-1].split("\\")[-1]
            self._check_workflow.setText(f"  ✓  Workflow loaded: {name}")
            self._check_workflow.setStyleSheet("color: #6ec46e; font-size: 11px; border: none;")
            # Hide the API format hint once workflow is loaded
            self._check_hint.setVisible(False)
        else:
            self._check_workflow.setText("  ✗  Load a workflow JSON file (API format)")
            self._check_workflow.setStyleSheet("color: #e06c6c; font-size: 11px; border: none;")
            self._check_hint.setVisible(True)

        # Hide the whole checklist once both conditions are met
        both_done = self._is_connected and self._manager.is_loaded
        self._checklist.setVisible(not both_done)

    def _refresh_generate_btn(self) -> None:
        """Enable Generate only when both connected and workflow is loaded."""
        ready = self._is_connected and self._manager.is_loaded
        self._generate_btn.setEnabled(ready)
        if not self._is_connected and not self._manager.is_loaded:
            self._generate_btn.setToolTip("Connect to ComfyUI and load a workflow to enable")
        elif not self._is_connected:
            self._generate_btn.setToolTip("Connect to a ComfyUI server to enable")
        elif not self._manager.is_loaded:
            self._generate_btn.setToolTip("Load a workflow JSON file to enable")
        else:
            self._generate_btn.setToolTip("Submit workflow to ComfyUI for generation")

    def set_control_state(
        self,
        has_running: bool,
        has_pending: bool,
        has_any: bool,
        connected: bool,
    ) -> None:
        """Update enabled state of the control buttons based on current job state."""
        active = has_running or has_pending
        self._stop_btn.setEnabled(connected and has_running)
        self._clear_queue_btn.setEnabled(connected and has_pending)
        self._stop_clear_btn.setEnabled(connected and active)
        self._retry_btn.setEnabled(connected and has_any)

    def set_connected(self, connected: bool) -> None:
        """Called by MainWindow when connection state changes."""
        self._is_connected = connected
        self._refresh_btn.setEnabled(connected)
        if not connected:
            self._server_options = {}
        self._update_checklist()
        self._refresh_generate_btn()

    def set_server_options(self, options: dict[str, list[str]]) -> None:
        """Called by MainWindow after fetching models/object_info from the server.

        ``options`` maps ComfyUI input names to lists of valid choices, e.g.::

            {
                "lora_name":    ["my_lora.safetensors", ...],
                "ckpt_name":    ["v1-5-pruned.safetensors", ...],
                "sampler_name": ["euler", "dpm_2", ...],
                "scheduler":    ["normal", "karras", ...],
            }
        """
        self._server_options = options
        # Repopulate forms if a workflow is already loaded so combos appear immediately.
        # Snapshot current values first so user edits survive the rebuild.
        if self._manager.is_loaded:
            snapshot = self.get_all_overrides()
            batch_snapshot = self._batch_spin.value()
            self._populate_forms()
            if snapshot:
                for form in self._node_forms:
                    node_data = snapshot.get(form._node.node_id)
                    if node_data and isinstance(node_data, dict):
                        form.apply_overrides(node_data)
            self._batch_spin.setValue(batch_snapshot)

    def get_workflow_manager(self) -> WorkflowManager:
        return self._manager
