from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, QRectF, QSizeF, QTimer
from PySide6.QtGui import QPixmap, QWheelEvent, QKeySequence, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QStackedWidget, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QFileDialog, QSizePolicy,
    QApplication, QToolButton,
)

from utils.image_utils import make_thumbnail

# Avoid a hard import cycle: ConfigManager is injected at runtime.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from utils.config_manager import ConfigManager

_THUMB_SIZE = 180

# Per-generation background colours — distinct but dark enough not to overpower the image.
_GEN_PALETTE: list[str] = [
    "#1c3a5c",  # steel blue
    "#1c4a2a",  # forest green
    "#4a1c4a",  # deep violet
    "#4a3800",  # dark amber
    "#004a4a",  # dark cyan
    "#5c1c1c",  # brick red
    "#2a1c5c",  # indigo
    "#3a3a00",  # olive
]

# Brighter alternative palette — more vivid, easier to distinguish at a glance.
_GEN_PALETTE_BRIGHT: list[str] = [
    "#2a6aaa",  # sky blue
    "#2a8040",  # emerald
    "#8030a0",  # violet
    "#b07000",  # golden amber
    "#007f7f",  # teal
    "#aa2525",  # crimson
    "#5040b0",  # indigo
    "#7a8800",  # olive-yellow
]


@dataclass(frozen=True)
class _ImageMeta:
    """Metadata snapshot for a single generated image, displayed in the detail strip."""

    filename: str = ""
    width: int = 0
    height: int = 0
    gen_time: float | None = None
    lora_name: str = ""
    workflow_name: str = ""
    created_at: str = ""
    prompt_id_short: str = ""


class _ThumbnailLabel(QLabel):
    """Clickable thumbnail label with an optional generation-time badge."""

    clicked = Signal(int)  # emits its index

    def __init__(
        self,
        index: int,
        pixmap: QPixmap,
        gen_time: float | None = None,
        bg_color: str = "#222",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        thumb = make_thumbnail(pixmap, _THUMB_SIZE)
        self.setPixmap(thumb)
        self.setFixedSize(_THUMB_SIZE + 4, _THUMB_SIZE + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"QLabel {{ border: 3px solid {bg_color}; border-radius: 4px; background: {bg_color}; }}"
            "QLabel:hover { border-color: #4a9eda; }"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if gen_time is not None:
            mins, secs = divmod(gen_time, 60)
            if mins >= 1:
                text = f"{int(mins)}m {secs:.0f}s"
            else:
                text = f"{gen_time:.1f}s"
            self._badge = QLabel(text, self)
            self._badge.setStyleSheet(
                "background: rgba(0,0,0,170); color: #e0e0e0; "
                "font-size: 10px; font-weight: bold; "
                "border-radius: 3px; padding: 1px 4px;"
            )
            self._badge.adjustSize()
            # Pin to bottom-right corner (inside the 2 px border)
            bw = self._badge.width()
            bh = self._badge.height()
            self._badge.move(self.width() - bw - 4, self.height() - bh - 4)
            self._badge.raise_()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._index)


class _ZoomableView(QGraphicsView):
    """QGraphicsView with mouse-wheel zoom and click-drag pan."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: QGraphicsPixmapItem | None = None
        self._user_zoomed: bool = False
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(self.renderHints() | self.renderHints().SmoothPixmapTransform)  # type: ignore[operator]
        self.setStyleSheet("background: #1a1a1a; border: none;")

    def set_bg_color(self, color: str) -> None:
        """Update the view background to reflect the generation group colour."""
        self.setStyleSheet(f'background: {color}; border: none;')

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._user_zoomed = False
        self._scene.clear()
        self._item = QGraphicsPixmapItem(pixmap)
        self._scene.addItem(self._item)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.resetTransform()
        self._fit()

    def _fit(self) -> None:
        """Fit the current item to the viewport. Safe to call any time."""
        if self._item and self.isVisible():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Defer fit to next event loop tick so Qt has finished the layout pass
        # and the viewport has its final geometry. Only fit if not manually zoomed.
        if not self._user_zoomed:
            QTimer.singleShot(0, self._fit)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Only auto-fit on resize if the user hasn't manually zoomed.
        if not self._user_zoomed:
            self._fit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._user_zoomed = True
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def keyPressEvent(self, event) -> None:
        # Forward left/right/escape navigation to the enclosing ImageViewer
        # (identified by the _nav_prev attribute) so keys work regardless
        # of which child widget holds focus.
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Escape):
            p = self.parentWidget()
            while p is not None:
                if hasattr(p, '_nav_prev'):
                    p.keyPressEvent(event)
                    return
                p = p.parentWidget()
        super().keyPressEvent(event)

    def current_pixmap(self) -> QPixmap | None:
        if self._item:
            return self._item.pixmap()
        return None


# ---------------------------------------------------------------------------
# Metadata overlay strip (shown in detail view)
# ---------------------------------------------------------------------------

class _MetaStrip(QWidget):
    """Semi-transparent metadata overlay pinned to the bottom of the detail view."""

    size_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "_MetaStrip { background: rgba(0,0,0,175); border-radius: 6px; "
            "border: 1px solid rgba(255,255,255,25); }"
        )
        self._expanded = False
        self._meta: _ImageMeta | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        compact_row = QHBoxLayout()
        compact_row.setSpacing(8)
        self._compact_label = QLabel(self)
        self._compact_label.setStyleSheet(
            "color: #e0e0e0; font-size: 11px; background: transparent;"
        )
        compact_row.addWidget(self._compact_label, stretch=1)

        self._toggle_btn = QToolButton(self)
        self._toggle_btn.setText("\u22ef")
        self._toggle_btn.setFixedSize(24, 18)
        self._toggle_btn.setStyleSheet(
            "QToolButton { background: rgba(255,255,255,30); color: #bbb; "
            "border-radius: 3px; padding: 0; font-size: 11px; }"
            "QToolButton:hover { background: rgba(255,255,255,60); color: #fff; }"
        )
        self._toggle_btn.setToolTip("Show more details")
        self._toggle_btn.clicked.connect(self._toggle_expand)
        compact_row.addWidget(self._toggle_btn)
        outer.addLayout(compact_row)

        self._detail_label = QLabel(self)
        self._detail_label.setStyleSheet(
            "color: #b8b8b8; font-size: 10px; background: transparent; font-family: monospace;"
        )
        self._detail_label.setWordWrap(False)
        self._detail_label.setVisible(False)
        outer.addWidget(self._detail_label)

    def set_meta(self, meta: _ImageMeta | None) -> None:
        self._meta = meta
        self._expanded = False
        self._detail_label.setVisible(False)
        self._toggle_btn.setText("\u22ef")
        self._toggle_btn.setToolTip("Show more details")
        if meta is None:
            self.setVisible(False)
            return
        self._refresh_text()
        self.setVisible(True)
        self.adjustSize()
        self.size_changed.emit()

    def _refresh_text(self) -> None:
        m = self._meta
        if not m:
            return
        parts: list[str] = [f"{m.width}\u00d7{m.height}"]
        if m.gen_time is not None:
            mins, secs = divmod(m.gen_time, 60)
            parts.append(f"{int(mins)}m {secs:.0f}s" if mins >= 1 else f"{m.gen_time:.1f}s")
        if m.lora_name:
            parts.append(f"LoRA: {m.lora_name}")
        if m.workflow_name:
            parts.append(m.workflow_name)
        self._compact_label.setText("  \u00b7  ".join(parts))

        rows: list[str] = [f"Resolution   {m.width} x {m.height}"]
        if m.gen_time is not None:
            mins, secs = divmod(m.gen_time, 60)
            rows.append("Gen time     " + (f"{int(mins)}m {secs:.0f}s" if mins >= 1 else f"{m.gen_time:.1f}s"))
        if m.lora_name:
            rows.append(f"LoRA         {m.lora_name}")
        if m.workflow_name:
            rows.append(f"Workflow     {m.workflow_name}")
        if m.created_at:
            rows.append(f"Generated    {m.created_at}")
        if m.prompt_id_short:
            rows.append(f"Prompt ID    {m.prompt_id_short}")
        if m.filename:
            rows.append(f"Filename     {m.filename}")
        self._detail_label.setText("\n".join(rows))

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._detail_label.setVisible(self._expanded)
        self._toggle_btn.setText("\u2715" if self._expanded else "\u22ef")
        self._toggle_btn.setToolTip("Collapse" if self._expanded else "Show more details")
        self.adjustSize()
        self.size_changed.emit()


# ---------------------------------------------------------------------------
# Detail page: _ZoomableView + overlaid prev/next arrow buttons
# ---------------------------------------------------------------------------

_NAV_BTN_STYLE = """
    QToolButton {
        background: rgba(0, 0, 0, 140);
        color: #ffffff;
        font-size: 28px;
        font-weight: bold;
        border: none;
        border-radius: 6px;
        padding: 4px 2px;
    }
    QToolButton:hover  { background: rgba(74, 158, 218, 200); }
    QToolButton:pressed { background: rgba(40, 100, 160, 230); }
    QToolButton:disabled { color: rgba(255,255,255,40); background: rgba(0,0,0,60); }
"""


class _DetailPage(QWidget):
    """_ZoomableView with prev/next arrow buttons overlaid on left/right edges."""

    prev_requested = Signal()
    next_requested = Signal()
    back_requested = Signal()

    _BTN_W = 44
    _BTN_H = 90

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The zoomable image view fills the whole widget
        self.view = _ZoomableView(self)
        self.view.setParent(self)

        # Overlay arrow buttons (no layout — positioned manually)
        self._prev_btn = QToolButton(self)
        self._prev_btn.setText("‹")
        self._prev_btn.setFixedSize(self._BTN_W, self._BTN_H)
        self._prev_btn.setStyleSheet(_NAV_BTN_STYLE)
        self._prev_btn.setToolTip("Previous image  (Left arrow)")
        self._prev_btn.clicked.connect(self.prev_requested)
        self._prev_btn.raise_()

        self._next_btn = QToolButton(self)
        self._next_btn.setText("›")
        self._next_btn.setFixedSize(self._BTN_W, self._BTN_H)
        self._next_btn.setStyleSheet(_NAV_BTN_STYLE)
        self._next_btn.setToolTip("Next image  (Right arrow)")
        self._next_btn.clicked.connect(self.next_requested)
        self._next_btn.raise_()

        # Metadata overlay strip pinned to the bottom
        self._meta_strip = _MetaStrip(self)
        self._meta_strip.size_changed.connect(self._position_meta_strip)
        self._meta_strip.setVisible(False)

        # Back-to-grid overlay button (upper-left, always visible in detail mode)
        self._back_overlay = QToolButton(self)
        self._back_overlay.setText("← Grid")
        self._back_overlay.setStyleSheet(
            "QToolButton { background: rgba(0,0,0,140); color: #ffffff; "
            "font-size: 13px; border: none; border-radius: 5px; padding: 4px 9px; } "
            "QToolButton:hover { background: rgba(74,158,218,200); } "
            "QToolButton:pressed { background: rgba(40,100,160,230); }"
        )
        self._back_overlay.setToolTip("Back to grid  (Escape)")
        self._back_overlay.clicked.connect(self.back_requested)
        self._back_overlay.adjustSize()
        self._back_overlay.raise_()

        # Single combined upper-right info overlay (All / Batch / LoRA)
        self._overlay_label = QLabel("", self)
        self._overlay_label.setStyleSheet(
            "QLabel { background: rgba(0,0,0,160); color: #c8c8c8; "
            "font-size: 13px; font-weight: bold; "
            "border-radius: 6px; padding: 6px 10px; }"
        )
        self._overlay_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._overlay_label.setVisible(False)

        self._position_buttons()
        self._position_meta_strip()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.view.setGeometry(0, 0, self.width(), self.height())
        self._position_buttons()
        self._position_meta_strip()
        self._position_overlays()

    def _position_buttons(self) -> None:
        mid_y = (self.height() - self._BTN_H) // 2
        margin = 10
        self._prev_btn.move(margin, mid_y)
        self._next_btn.move(self.width() - self._BTN_W - margin, mid_y)

    def set_nav_state(self, index: int, total: int) -> None:
        """Show/hide arrows and set enabled state based on position in list."""
        multi = total > 1
        self._prev_btn.setVisible(multi)
        self._next_btn.setVisible(multi)
        if multi:
            self._prev_btn.setEnabled(index > 0)
            self._next_btn.setEnabled(index < total - 1)
            self._prev_btn.raise_()
            self._next_btn.raise_()

    def hide_nav(self) -> None:
        """Hide nav buttons (used during live preview)."""
        self._prev_btn.setVisible(False)
        self._next_btn.setVisible(False)

    def set_meta(
        self,
        meta: _ImageMeta | None,
        show_lora: bool = False,
        batch_pos: int = 0,
        batch_total: int = 0,
        show_batch: bool = False,
        all_pos: int = 0,
        all_total: int = 0,
        show_all: bool = False,
    ) -> None:
        """Update the metadata strip and upper-right overlays for the current image."""
        self._meta_strip.set_meta(meta)
        self._position_meta_strip()
        import os as _os
        lora = (meta.lora_name if meta else "").strip()
        lora_display = _os.path.splitext(_os.path.basename(lora))[0] if lora else ""
        # Build combined info block (top-to-bottom: All, Batch, LoRA)
        lines: list[str] = []
        if show_all and all_total > 1:
            lines.append(f"All: ({all_pos} of {all_total})")
        if show_batch and batch_total > 1:
            lines.append(f"Batch: ({batch_pos} / {batch_total})")
        if show_lora and lora_display:
            lines.append(f"LoRA: {lora_display}")
        if lines:
            self._overlay_label.setText("\n".join(lines))
            self._overlay_label.adjustSize()
            self._overlay_label.setVisible(True)
        else:
            self._overlay_label.setVisible(False)
        self._position_overlays()

    def _position_overlays(self) -> None:
        """Position the back button (upper-left) and info block (upper-right)."""
        margin = 12
        self._back_overlay.move(margin, margin)
        self._back_overlay.raise_()
        if self._overlay_label.isVisible():
            x = self.width() - self._overlay_label.width() - margin
            self._overlay_label.move(max(x, margin), margin)
            self._overlay_label.raise_()

    def _position_meta_strip(self) -> None:
        if not self._meta_strip.isVisible():
            return
        max_w = min(self.width() - 40, 700)
        self._meta_strip.setMaximumWidth(max_w)
        self._meta_strip.adjustSize()
        sw = self._meta_strip.width()
        sh = self._meta_strip.height()
        x = (self.width() - sw) // 2
        y = self.height() - sh - 16
        self._meta_strip.move(max(x, 0), max(y, 0))
        self._meta_strip.raise_()


class ImageViewer(QWidget):
    """Two-mode image viewer: thumbnail grid and full-size detail view."""

    load_workflow_requested = Signal(bytes)  # emits raw PNG bytes of the current image

    def __init__(
        self,
        cfg_mgr: "ConfigManager | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg_mgr = cfg_mgr
        self._pixmaps: list[QPixmap] = []
        self._filenames: list[str] = []
        self._raw_bytes: list[bytes] = []
        self._current_index: int = -1
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)
        self._back_btn = QPushButton("← Grid", self)
        self._back_btn.setFixedWidth(70)
        self._back_btn.setVisible(False)
        self._back_btn.clicked.connect(self.show_grid)

        self._save_btn = QPushButton("Save As…", self)
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save)

        self._copy_btn = QPushButton("Copy", self)
        self._copy_btn.setVisible(False)
        self._copy_btn.clicked.connect(self._on_copy)

        self._load_wf_btn = QPushButton("Load Workflow", self)
        self._load_wf_btn.setVisible(False)
        self._load_wf_btn.setToolTip("Extract and load the workflow embedded in this image")
        self._load_wf_btn.clicked.connect(self._on_load_workflow)

        self._clear_btn = QPushButton("Clear Images", self)
        self._clear_btn.setVisible(False)
        self._clear_btn.setToolTip("Remove all images from the grid")
        self._clear_btn.clicked.connect(self.clear)

        self._info_label = QLabel("No images", self)
        self._info_label.setStyleSheet("color: #888; font-size: 11px;")
        self._info_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        toolbar.addWidget(self._back_btn)
        toolbar.addWidget(self._info_label)
        toolbar.addStretch()
        toolbar.addWidget(self._clear_btn)
        toolbar.addWidget(self._copy_btn)
        toolbar.addWidget(self._load_wf_btn)
        toolbar.addWidget(self._save_btn)
        root.addLayout(toolbar)

        # --- Stacked: grid vs detail ---
        self._stack = QStackedWidget(self)

        # Grid page
        self._grid_scroll = QScrollArea(self)
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._grid_container = QWidget()
        self._grid_layout = _FlowLayout(self._grid_container)
        self._grid_scroll.setWidget(self._grid_container)
        self._stack.addWidget(self._grid_scroll)  # index 0 = grid

        # Detail page (zoomable view + overlay nav arrows)
        self._detail_page = _DetailPage(self)
        self._detail_page.prev_requested.connect(self._nav_prev)
        self._detail_page.next_requested.connect(self._nav_next)
        self._detail_page.back_requested.connect(self.show_grid)
        self._detail_view = self._detail_page.view   # kept for compat
        self._stack.addWidget(self._detail_page)     # index 1 = detail

        root.addWidget(self._stack, stretch=1)

        # Per-generation colour tracking
        self._gen_color_map: dict[str, str] = {}
        self._next_color_index: int = 0
        self._index_colors: list[str] = []
        self._index_meta: list[_ImageMeta | None] = []
        self._index_generation_ids: list[str] = []
        self._index_raw_bytes: list[bytes] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add_image(
        self,
        pixmap: QPixmap,
        filename: str = "",
        gen_time: float | None = None,
        generation_id: str = "",
        meta: _ImageMeta | None = None,
        raw_bytes: bytes | None = None,
    ) -> None:
        """Append an image to the viewer grid."""
        # Pick palette based on current config setting
        palette = _GEN_PALETTE
        if self._cfg_mgr and getattr(self._cfg_mgr.config, "thumbnail_palette", "dark") == "bright":
            palette = _GEN_PALETTE_BRIGHT
        # Assign a stable bg colour for this generation
        if generation_id and generation_id not in self._gen_color_map:
            self._gen_color_map[generation_id] = palette[
                self._next_color_index % len(palette)
            ]
            self._next_color_index += 1
        bg_color = self._gen_color_map.get(generation_id, "#222")

        index = len(self._pixmaps)
        self._pixmaps.append(pixmap)
        self._filenames.append(filename)
        self._index_colors.append(bg_color)
        self._index_meta.append(meta)
        self._index_generation_ids.append(generation_id)
        self._index_raw_bytes.append(raw_bytes or b"")
        thumb = _ThumbnailLabel(index, pixmap, gen_time, bg_color, self._grid_container)
        thumb.clicked.connect(self._show_detail)
        self._grid_layout.addWidget(thumb)
        total = len(self._pixmaps)
        self._info_label.setText(f"{total} image(s)")
        if total == 1 and self._stack.currentIndex() == 0:
            self._clear_btn.setVisible(True)
        # If detail view is open, refresh nav state so the › button enables for new images.
        if self._stack.currentIndex() == 1 and self._current_index >= 0:
            self._detail_page.set_nav_state(self._current_index, total)
            # Also refresh the "N / total — name" label with the new total.
            name = self._filenames[self._current_index] or f"image_{self._current_index + 1}"
            self._info_label.setText(f"{self._current_index + 1} / {total}  \u2014  {name}")

    def show_preview(self, pixmap: QPixmap) -> None:
        """Show a live (temporary) preview image in the detail view."""
        # Switch stack first so the viewport has its real size when set_pixmap calls _fit.
        self._stack.setCurrentIndex(1)
        self._back_btn.setVisible(True)
        self._save_btn.setVisible(False)
        self._copy_btn.setVisible(False)
        self._load_wf_btn.setVisible(False)
        self._clear_btn.setVisible(False)
        self._detail_page.hide_nav()
        self._detail_page.set_meta(None, show_lora=False)
        self._current_index = -1
        self._detail_view.set_bg_color("#1a1a1a")
        self._detail_view.set_pixmap(pixmap)

    def show_grid(self) -> None:
        self._stack.setCurrentIndex(0)
        self._back_btn.setVisible(False)
        self._save_btn.setVisible(False)
        self._copy_btn.setVisible(False)
        self._load_wf_btn.setVisible(False)
        self._clear_btn.setVisible(bool(self._pixmaps))

    def clear(self) -> None:
        self._pixmaps.clear()
        self._filenames.clear()
        self._index_colors.clear()
        self._index_meta.clear()
        self._index_generation_ids.clear()
        self._index_raw_bytes.clear()
        self._current_index = -1
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._info_label.setText("No images")
        self.show_grid()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _show_detail(self, index: int) -> None:
        if index < 0 or index >= len(self._pixmaps):
            return
        self._current_index = index
        # Switch stack first so the viewport is at its final size before fitInView.
        self._stack.setCurrentIndex(1)
        self._back_btn.setVisible(True)
        self._save_btn.setVisible(True)
        self._copy_btn.setVisible(True)
        has_bytes = bool(self._index_raw_bytes[index] if index < len(self._index_raw_bytes) else b"")
        self._load_wf_btn.setVisible(has_bytes)
        self._clear_btn.setVisible(False)
        name = self._filenames[index] or f"image_{index + 1}"
        total = len(self._pixmaps)
        self._info_label.setText(f"{index + 1} / {total}  —  {name}")
        self._detail_page.set_nav_state(index, total)
        bg = self._index_colors[index] if index < len(self._index_colors) else "#1a1a1a"
        self._detail_view.set_bg_color(bg)
        show_lora = bool(self._cfg_mgr and getattr(self._cfg_mgr.config, "show_lora_overlay", True))
        show_batch = bool(self._cfg_mgr and getattr(self._cfg_mgr.config, "show_batch_position", True))
        show_all = bool(self._cfg_mgr and getattr(self._cfg_mgr.config, "show_all_position", True))
        gen_id = self._index_generation_ids[index] if index < len(self._index_generation_ids) else ""
        batch_pos = batch_total = 0
        if gen_id:
            batch_total = sum(1 for g in self._index_generation_ids if g == gen_id)
            batch_pos = sum(1 for i2, g in enumerate(self._index_generation_ids) if g == gen_id and i2 <= index)
        self._detail_page.set_meta(
            self._index_meta[index] if index < len(self._index_meta) else None,
            show_lora=show_lora,
            batch_pos=batch_pos,
            batch_total=batch_total,
            show_batch=show_batch,
            all_pos=index + 1,
            all_total=total,
            show_all=show_all,
        )
        self._detail_view.set_pixmap(self._pixmaps[index])
        self.setFocus()

    def _nav_prev(self) -> None:
        self._show_detail(self._current_index - 1)

    def _nav_next(self) -> None:
        self._show_detail(self._current_index + 1)

    def keyPressEvent(self, event) -> None:
        if self._stack.currentIndex() == 1:
            if event.key() == Qt.Key.Key_Escape:
                self.show_grid()
                return
            if self._current_index >= 0:
                if event.key() == Qt.Key.Key_Left:
                    self._nav_prev()
                    return
                if event.key() == Qt.Key.Key_Right:
                    self._nav_next()
                    return
        super().keyPressEvent(event)

    def _on_save(self) -> None:
        pixmap = self._detail_view.current_pixmap()
        if not pixmap:
            return
        start_dir = ""
        if self._cfg_mgr:
            start_dir = self._cfg_mgr.config.last_image_save_dir
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Image", start_dir, "PNG Images (*.png);;JPEG Images (*.jpg)"
        )
        if path:
            pixmap.save(path)
            if self._cfg_mgr:
                import os as _os
                self._cfg_mgr.update(last_image_save_dir=_os.path.dirname(path))

    def _on_copy(self) -> None:
        pixmap = self._detail_view.current_pixmap()
        if pixmap:
            QGuiApplication.clipboard().setPixmap(pixmap)

    def _on_load_workflow(self) -> None:
        idx = self._current_index
        if idx < 0 or idx >= len(self._index_raw_bytes):
            return
        raw = self._index_raw_bytes[idx]
        if raw:
            self.load_workflow_requested.emit(raw)


# ------------------------------------------------------------------
# Simple flow layout (wraps thumbnails like a CSS flex-wrap row)
# ------------------------------------------------------------------

from PySide6.QtCore import QRect, QPoint
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy as SP


class _FlowLayout(QLayout):
    """A layout that wraps its children into rows."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        from PySide6.QtCore import QSize
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        row_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > effective.right() and row_height > 0:
                x = effective.x()
                y += row_height + self._spacing
                next_x = x + hint.width() + self._spacing
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + m.bottom()
