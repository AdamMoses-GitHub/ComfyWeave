from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QFileDialog,
    QDialogButtonBox, QGroupBox, QFormLayout,
)

from models.config_model import AppConfig


class SettingsDialog(QDialog):
    """Modal settings dialog. Caller reads .config after exec_() returns Accepted."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.config = AppConfig(**config.__dict__)  # work on a copy
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # --- Connection ---
        conn_group = QGroupBox("Connection", self)
        conn_form = QFormLayout(conn_group)
        self._url_edit = QLineEdit(self)
        self._url_edit.setPlaceholderText("http://127.0.0.1:8188")
        conn_form.addRow("Server URL:", self._url_edit)
        self._autoconnect_cb = QCheckBox("Auto-connect on startup", self)
        conn_form.addRow("", self._autoconnect_cb)
        root.addWidget(conn_group)

        # --- Files ---
        file_group = QGroupBox("Paths", self)
        file_form = QFormLayout(file_group)
        outdir_row = QHBoxLayout()
        self._outdir_edit = QLineEdit(self)
        self._outdir_browse = QPushButton("Browse…", self)
        self._outdir_browse.setFixedWidth(80)
        self._outdir_browse.clicked.connect(self._browse_output_dir)
        outdir_row.addWidget(self._outdir_edit)
        outdir_row.addWidget(self._outdir_browse)
        file_form.addRow("Output Directory:", outdir_row)
        root.addWidget(file_group)

        # --- Appearance ---
        ui_group = QGroupBox("Appearance", self)
        ui_form = QFormLayout(ui_group)
        self._theme_combo = QComboBox(self)
        self._theme_combo.addItems(["dark", "light"])
        ui_form.addRow("Theme:", self._theme_combo)
        self._max_history = QLineEdit(self)
        ui_form.addRow("Max History Items:", self._max_history)
        self._thumb_palette_combo = QComboBox(self)
        self._thumb_palette_combo.addItem("Dark  (subtle, low contrast)", userData="dark")
        self._thumb_palette_combo.addItem("Bright  (vivid, easy to distinguish)", userData="bright")
        self._thumb_palette_combo.setToolTip(
            "Background colour style for generation-group thumbnails in the grid view."
        )
        ui_form.addRow("Thumbnail Colours:", self._thumb_palette_combo)
        root.addWidget(ui_group)

        # --- Generation ---
        gen_group = QGroupBox("Generation", self)
        gen_form = QFormLayout(gen_group)

        self._dim_divisor_combo = QComboBox(self)
        _DIM_OPTIONS = [
            (8,  "Minimum — 8   (required for VAE encoding/decoding)"),
            (16, "Recommended — 16  (better alignment for most KSamplers)"),
            (64, "Optimal — 64  (matches SD/SDXL training architecture)"),
        ]
        for val, label in _DIM_OPTIONS:
            self._dim_divisor_combo.addItem(label, userData=val)
        self._dim_divisor_combo.setToolTip(
            "Width and height inputs will be automatically snapped\n"
            "to the nearest multiple of this value.\n"
            "Takes effect when a workflow is next loaded."
        )
        gen_form.addRow("Dimension Divisor:", self._dim_divisor_combo)

        hint = QLabel(
            "Width/height values will snap to the nearest multiple of the chosen divisor."
            "\nChange takes effect when the workflow is reloaded.",
            gen_group,
        )
        hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setWordWrap(True)
        gen_form.addRow("", hint)
        root.addWidget(gen_group)

        # --- Single Image View ---
        siv_group = QGroupBox("Single Image View", self)
        siv_form = QFormLayout(siv_group)
        self._lora_overlay_cb = QCheckBox("Show LoRA name overlay", self)
        self._lora_overlay_cb.setToolTip(
            "When a LoRA was used, display its name as a bold badge\n"
            "in the upper-right corner of the single image view."
        )
        siv_form.addRow("", self._lora_overlay_cb)
        self._batch_pos_cb = QCheckBox("Show batch position  Batch: (X / Y)", self)
        self._batch_pos_cb.setToolTip(
            "Show the image's position within its generation batch\n"
            "(e.g. Batch: (2 / 4)) in the upper-right corner of the single image view.\n"
            "Hidden automatically when batch size is 1."
        )
        siv_form.addRow("", self._batch_pos_cb)
        self._all_pos_cb = QCheckBox("Show position across all images  All: (X of Y)", self)
        self._all_pos_cb.setToolTip(
            "Show the image's absolute position across all images in the session\n"
            "(e.g. All: (7 of 12)) in the upper-right corner of the single image view.\n"
            "Hidden automatically when there is only one image."
        )
        siv_form.addRow("", self._all_pos_cb)
        root.addWidget(siv_group)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate(self) -> None:
        self._url_edit.setText(self.config.server_url)
        self._autoconnect_cb.setChecked(self.config.auto_connect)
        self._outdir_edit.setText(self.config.output_dir)
        idx = self._theme_combo.findText(self.config.theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._max_history.setText(str(self.config.max_history_items))
        for i in range(self._thumb_palette_combo.count()):
            if self._thumb_palette_combo.itemData(i) == getattr(self.config, "thumbnail_palette", "dark"):
                self._thumb_palette_combo.setCurrentIndex(i)
                break
        # Select the matching divisor entry by stored userData value
        for i in range(self._dim_divisor_combo.count()):
            if self._dim_divisor_combo.itemData(i) == self.config.dimension_divisor:
                self._dim_divisor_combo.setCurrentIndex(i)
                break
        self._lora_overlay_cb.setChecked(getattr(self.config, "show_lora_overlay", True))
        self._batch_pos_cb.setChecked(getattr(self.config, "show_batch_position", True))
        self._all_pos_cb.setChecked(getattr(self.config, "show_all_position", True))

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if path:
            self._outdir_edit.setText(path)

    def _on_accept(self) -> None:
        self.config.server_url     = self._url_edit.text().strip()
        self.config.auto_connect   = self._autoconnect_cb.isChecked()
        self.config.output_dir     = self._outdir_edit.text().strip()
        self.config.theme          = self._theme_combo.currentText()
        try:
            self.config.max_history_items = int(self._max_history.text())
        except ValueError:
            pass
        self.config.thumbnail_palette  = self._thumb_palette_combo.currentData()
        self.config.dimension_divisor = self._dim_divisor_combo.currentData()
        self.config.show_lora_overlay = self._lora_overlay_cb.isChecked()
        self.config.show_batch_position = self._batch_pos_cb.isChecked()
        self.config.show_all_position = self._all_pos_cb.isChecked()
        self.accept()
