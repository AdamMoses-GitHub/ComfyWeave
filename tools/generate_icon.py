"""Generate the ComfyWeave application icon.

Produces:
  assets/icon.png  (256×256)
  assets/icon.ico  (multi-size: 16, 32, 48, 64, 128, 256)

Run once from the project root:
  python tools/generate_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Use Qt for rendering so no Pillow dependency is needed
# ---------------------------------------------------------------------------
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QImage, QPainter,
    QPainterPath, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QApplication

SIZES = [16, 32, 48, 64, 128, 256]
OUT_DIR = Path(__file__).resolve().parent.parent / "assets"


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # --- Background: rounded square, deep blue ---
    radius = size * 0.18
    bg = QColor("#1A56DB")        # vivid blue
    p.setBrush(bg)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, radius, radius)

    # --- Letter "C" ---
    font = QFont("Segoe UI", int(size * 0.62), QFont.Weight.Bold)
    p.setFont(font)
    p.setPen(QColor("#FBBF24"))   # amber-yellow
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "C")

    p.end()
    return img


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # PNG at max size
    big = render(256)
    png_path = OUT_DIR / "icon.png"
    big.save(str(png_path), "PNG")
    print(f"  Saved {png_path}")

    # ICO with multiple sizes
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(QPixmap.fromImage(render(s)))

    ico_path = OUT_DIR / "icon.ico"
    # Qt can't write .ico directly — save each size as PNG and use Pillow if
    # available, otherwise fall back to writing a 256-px PNG named .ico
    try:
        from PIL import Image as PILImage

        pil_images: list = []
        for s in SIZES:
            img = render(s)
            buf = img.bits().tobytes()
            pil = PILImage.frombytes("RGBA", (s, s), buf, "raw", "BGRA")
            pil_images.append(pil)

        pil_images[0].save(
            str(ico_path),
            format="ICO",
            sizes=[(s, s) for s in SIZES],
            append_images=pil_images[1:],
        )
        print(f"  Saved {ico_path}  (multi-size ICO via Pillow)")
    except ImportError:
        # Pillow not available — save 256-px PNG as .ico substitute
        big.save(str(ico_path), "PNG")
        print(f"  Saved {ico_path}  (PNG fallback — install Pillow for a real ICO)")

    print("Done.")


if __name__ == "__main__":
    main()
