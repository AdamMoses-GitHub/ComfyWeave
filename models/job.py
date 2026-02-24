from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional


class JobStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class ImageRef:
    """Reference to a generated image as returned by ComfyUI history/output."""

    filename: str
    subfolder: str
    type: str  # "output" | "input" | "temp"


@dataclass
class Job:
    """Represents a single generation job submitted to ComfyUI."""

    prompt_id: str
    client_id: str
    workflow_snapshot: dict
    workflow_path: str = ""

    status: JobStatus = JobStatus.PENDING
    progress_value: int = 0
    progress_max: int = 1
    current_node: str = ""
    error_message: str = ""

    output_images: list[ImageRef] = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None   # set when execution actually begins
    completed_at: Optional[datetime] = None

    # Multi-LoRA mode: display label for which LoRA this job used (empty = not a multi-LoRA run)
    lora_name: str = ""

    # Groups all batch iterations of the same LoRA pass under one ID for thumbnail colouring.
    generation_group_id: str = ""

    @property
    def display_id(self) -> str:
        """Short truncated prompt_id for display."""
        return self.prompt_id[:8]

    @property
    def gen_time(self) -> float | None:
        """Wall-clock seconds from execution start to completion, or None if unknown."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def duration_str(self) -> str:
        end = self.completed_at or datetime.now()
        delta = end - self.created_at
        secs = int(delta.total_seconds())
        m, s = divmod(secs, 60)
        return f"{m}m {s:02d}s" if m else f"{s}s"

    @property
    def progress_pct(self) -> int:
        if self.progress_max == 0:
            return 0
        return int(100 * self.progress_value / self.progress_max)
