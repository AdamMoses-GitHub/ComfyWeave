from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from core.exceptions import ComfyUIError


# Node classes we surface as editable in the workflow panel.
# Add entries here whenever a new node type should be user-editable.
_EDITABLE_NODE_CLASSES = {
    # Samplers
    "KSampler",
    "KSamplerAdvanced",
    # Text conditioning
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CLIPTextEncodeSDXLRefiner",
    # Model / checkpoint loaders
    "CheckpointLoaderSimple",
    "CheckpointLoader",
    "UNETLoader",
    "DualCLIPLoader",
    "CLIPLoader",
    # LoRA / adapters
    "LoraLoader",
    "LoraLoaderModelOnly",
    # VAE
    "VAELoader",
    "VAEDecode",
    "VAEEncode",
    # Latent image (resolution) nodes — this is the most common place for width/height
    "EmptyLatentImage",
    "EmptySD3LatentImage",
    "EmptyHunyuanLatentVideo",
    "EmptyMochiLatentVideo",
    "EmptyLTXVLatentVideo",
    "EmptyCogVideoXLatentVideo",
    "EmptyCogVideoXVideo",
    "LatentUpscale",
    "LatentUpscaleBy",
    # Output
    "SaveImage",
    "PreviewImage",
    # Upscaling
    "UpscaleModelLoader",
    "ImageUpscaleWithModel",
}

# Input names that should be treated as "primary" / shown prominently
_PRIMARY_INPUTS = {"text", "ckpt_name", "seed", "steps", "cfg", "sampler_name",
                   "scheduler", "denoise", "width", "height", "batch_size"}


class EditableNode:
    """Represents one workflow node whose inputs can be overridden via the UI."""

    def __init__(self, node_id: str, class_type: str, inputs: dict) -> None:
        self.node_id = node_id
        self.class_type = class_type
        self.inputs = inputs  # original input values
        self.title: str = ""  # from _meta.title if present

    def __repr__(self) -> str:
        return f"EditableNode({self.node_id}, {self.class_type})"


class WorkflowManager:
    """Loads, validates, and prepares ComfyUI workflow JSON for submission."""

    def __init__(self) -> None:
        self._raw: dict = {}
        self._path: str = ""

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_from_file(self, path: str) -> None:
        """Parse and validate a workflow JSON file exported from ComfyUI."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {path}")
        if file_path.suffix.lower() != ".json":
            raise ValueError("Workflow file must be a .json file")

        with file_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        self._validate(data)
        self._raw = data
        self._path = path

    def load_from_dict(self, data: dict) -> None:
        """Load workflow from an already-parsed dict (e.g. from history)."""
        self._validate(data)
        self._raw = data
        self._path = ""

    @property
    def is_loaded(self) -> bool:
        return bool(self._raw)

    @property
    def path(self) -> str:
        return self._path

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_editable_nodes(self) -> list[EditableNode]:
        """Return nodes whose class_type is in the editable set."""
        nodes: list[EditableNode] = []
        for node_id, node_data in self._raw.items():
            class_type = node_data.get("class_type", "")
            if class_type not in _EDITABLE_NODE_CLASSES:
                continue
            inputs = node_data.get("inputs", {})
            # Filter out link references (lists) — only keep literal values
            literal_inputs = {
                k: v for k, v in inputs.items()
                if not isinstance(v, list)
            }
            node = EditableNode(node_id, class_type, literal_inputs)
            node.title = node_data.get("_meta", {}).get("title", class_type)
            nodes.append(node)
        # Sort: primary-interest nodes first, then alphabetically by class
        nodes.sort(key=lambda n: (n.class_type not in {"KSampler", "CLIPTextEncode"}, n.class_type))
        return nodes

    def get_all_node_ids(self) -> list[str]:
        return list(self._raw.keys())

    # ------------------------------------------------------------------
    # Building the payload
    # ------------------------------------------------------------------

    def apply_overrides(self, overrides: dict[str, dict[str, Any]]) -> dict:
        """Return a copy of the workflow with node input overrides applied.

        ``overrides`` format: { "<node_id>": { "<input_name>": <value>, ... }, ... }
        """
        workflow = copy.deepcopy(self._raw)
        for node_id, input_patch in overrides.items():
            if node_id in workflow:
                workflow[node_id]["inputs"].update(input_patch)
        return workflow

    def to_prompt_payload(self, client_id: str, overrides: dict | None = None) -> dict:
        """Build the full ``POST /prompt`` body dict."""
        workflow = self.apply_overrides(overrides or {})
        return {
            "prompt": workflow,
            "client_id": client_id,
            "extra_data": {"extra_pnginfo": {"workflow": workflow}},
        }

    def raw_copy(self) -> dict:
        return copy.deepcopy(self._raw)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(data: Any) -> None:
        if not isinstance(data, dict):
            raise ComfyUIError("Workflow JSON must be a top-level object (dict).")
        if not data:
            raise ComfyUIError("Workflow JSON is empty.")

        # Detect the regular UI workflow format (has "nodes", "links", "version" keys)
        ui_format_keys = {"nodes", "links", "version", "last_node_id", "last_link_id"}
        if ui_format_keys.intersection(data.keys()):
            raise ComfyUIError(
                "This looks like a standard ComfyUI workflow file, not an API-format file.\n\n"
                "To get the correct format:\n"
                "  1. Open ComfyUI in your browser\n"
                "  2. Go to Settings → Enable Dev Mode Options\n"
                "  3. In the workflow menu (top-right), choose \"Save (API Format)\"\n\n"
                "The API format file has node IDs as top-level keys (e.g. \"1\", \"2\", …)."
            )

        # Each value should be a node dict with class_type
        for key, val in data.items():
            if not isinstance(val, dict):
                raise ComfyUIError(
                    f"Workflow node '{key}' has an unexpected value (expected a dict, got {type(val).__name__}).\n\n"
                    "Make sure you export the workflow using \"Save (API Format)\" from ComfyUI."
                )
