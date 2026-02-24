from __future__ import annotations

import json
import os
from pathlib import Path

from models.config_model import AppConfig


def _config_path() -> Path:
    """Return the path to settings.json, stored beside the project config/ dir."""
    base = Path(__file__).resolve().parent.parent / "config"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


class ConfigManager:
    """Manages loading and saving of :class:`AppConfig` to/from a JSON file."""

    def __init__(self) -> None:
        self._path = _config_path()
        self.config: AppConfig = AppConfig()

    def load(self) -> AppConfig:
        """Load config from disk, filling missing keys with defaults."""
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # Apply loaded values over defaults (missing keys use dataclass defaults)
                defaults = AppConfig.__dataclass_fields__
                kwargs = {k: data[k] for k in defaults if k in data}
                self.config = AppConfig(**kwargs)
            except Exception:
                # Corrupted config — fall back to defaults silently
                self.config = AppConfig()
        else:
            self.config = AppConfig()
        return self.config

    def save(self) -> None:
        """Persist current config to disk."""
        data = {
            k: getattr(self.config, k)
            for k in AppConfig.__dataclass_fields__
        }
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    def update(self, **kwargs) -> None:
        """Update one or more config fields and save."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self.save()
