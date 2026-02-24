from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppConfig:
    """Persistent application settings serialised to settings.json."""

    server_url: str = "http://127.0.0.1:8188"
    output_dir: str = ""
    last_workflow_path: str = ""
    auto_connect: bool = False
    theme: str = "dark"  # "dark" | "light"
    window_x: int = 100
    window_y: int = 100
    window_width: int = 1400
    window_height: int = 900
    splitter_left_width: int = 400
    max_history_items: int = 100

    # Batch defaults (reserved for batch execution feature)
    batch_default_count: int = 1
    batch_vary_seed: bool = True

    # Dimension snapping for width/height inputs
    # Allowed values: 8, 16, 64  (see SettingsDialog for explanation)
    dimension_divisor: int = 64

    # Thumbnail background colour palette in the grid view
    # Allowed values: "dark" | "bright"
    thumbnail_palette: str = "dark"

    # Single image view options
    show_lora_overlay: bool = True    # show LoRA name badge in upper-right of detail view
    show_batch_position: bool = True  # show Batch: (X / Y) badge in upper-right
    show_all_position: bool = True    # show All: (X of Y) badge in upper-right

    # Remembered file browser directories
    last_workflow_dir: str = ""       # starting dir for workflow JSON picker
    last_image_save_dir: str = ""     # starting dir for image Save As dialog

    # Last-session workflow form state (restored on startup)
    batch_count: int = 1
    workflow_overrides: dict = field(default_factory=dict)  # {node_id: {input_name: value}}
