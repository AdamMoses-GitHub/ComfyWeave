from __future__ import annotations

from typing import Any


class ComfyUIError(Exception):
    """Raised when the ComfyUI API returns an error response."""

    def __init__(self, message: str, status_code: int = 0, detail: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ComfyUIConnectionError(ComfyUIError):
    """Raised when the ComfyUI server cannot be reached."""
