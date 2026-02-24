from __future__ import annotations

import json
from pathlib import Path


def _library_path() -> Path:
    base = Path(__file__).resolve().parent.parent / "config"
    base.mkdir(parents=True, exist_ok=True)
    return base / "text_blocks.json"


class TextBlockManager:
    """Persists per-field anonymous text block libraries to config/text_blocks.json.

    The on-disk schema is::

        {
            "CLIP Text Encode (Prompt)_text": ["block text 1", "block text 2", ...],
            "Negative_text": [...],
            ...
        }

    Field keys are ``{node_title}_{input_name}``.
    """

    def __init__(self) -> None:
        self._path = _library_path()
        self._data: dict[str, list[str]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict):
                    self._data = {
                        k: v for k, v in raw.items()
                        if isinstance(k, str) and isinstance(v, list)
                    }
            except Exception:
                self._data = {}

    def _save(self) -> None:
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_blocks(self, field_key: str) -> list[str]:
        """Return a copy of the text block list for *field_key*."""
        return list(self._data.get(field_key, []))

    def set_blocks(self, field_key: str, blocks: list[str]) -> None:
        """Replace the entire block list for *field_key* and persist."""
        self._data[field_key] = list(blocks)
        self._save()

    def add_block_if_new(self, field_key: str, text: str) -> int | None:
        """Append *text* if not already in the list.

        Returns the index at which the text lives (new or existing),
        or ``None`` if *text* is empty/whitespace.
        """
        text = text.strip()
        if not text:
            return None
        blocks = self._data.setdefault(field_key, [])
        if text in blocks:
            return blocks.index(text)
        blocks.append(text)
        self._save()
        return len(blocks) - 1

    def remove_block(self, field_key: str, index: int) -> None:
        """Remove the block at *index* for *field_key* and persist."""
        blocks = self._data.get(field_key, [])
        if 0 <= index < len(blocks):
            blocks.pop(index)
            self._data[field_key] = blocks
            self._save()

    def move_block(self, field_key: str, from_index: int, to_index: int) -> None:
        """Move the block at *from_index* to *to_index* and persist."""
        blocks = self._data.get(field_key, [])
        n = len(blocks)
        if 0 <= from_index < n and 0 <= to_index < n and from_index != to_index:
            block = blocks.pop(from_index)
            blocks.insert(to_index, block)
            self._data[field_key] = blocks
            self._save()

    def update_block(self, field_key: str, index: int, new_text: str) -> None:
        """Update the text of the block at *index* and persist."""
        blocks = self._data.get(field_key, [])
        if 0 <= index < len(blocks):
            blocks[index] = new_text
            self._data[field_key] = blocks
            self._save()
