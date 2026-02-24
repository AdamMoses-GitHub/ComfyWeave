from __future__ import annotations

from io import BytesIO

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap


def bytes_to_pixmap(data: bytes) -> QPixmap:
    """Convert raw image bytes (PNG/JPEG/WebP) to a QPixmap."""
    image = QImage()
    image.loadFromData(data)
    return QPixmap.fromImage(image)


def make_thumbnail(pixmap: QPixmap, size: int = 200) -> QPixmap:
    """Scale a QPixmap to a square thumbnail while keeping aspect ratio."""
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
