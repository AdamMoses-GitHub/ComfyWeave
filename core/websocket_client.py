from __future__ import annotations

import asyncio
import json
import struct
import uuid
from typing import Optional

import websockets
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from utils.image_utils import bytes_to_pixmap


_RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]  # seconds, capped at last value


class WebSocketClient(QObject):
    """Persistent WebSocket connection to ComfyUI.

    Emits Qt signals so UI components can connect without threading concerns.
    The async loop is managed by qasync.
    """

    # Signals
    connected = Signal()
    disconnected = Signal()
    connection_error = Signal(str)

    queue_status_changed = Signal(int)          # queue_remaining

    execution_started = Signal(str)             # prompt_id
    execution_cached = Signal(str, list)        # prompt_id, [node_ids]
    node_executing = Signal(str, str)           # prompt_id, node_id
    node_executed = Signal(str, str, dict)      # prompt_id, node_id, output
    execution_finished = Signal(str)            # prompt_id
    execution_error = Signal(str, str)          # prompt_id, error_message
    execution_interrupted = Signal(str)         # prompt_id

    progress = Signal(str, int, int, str)       # prompt_id, value, max, node_id
    preview_image = Signal(str, QPixmap)        # prompt_id, pixmap (live preview)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.client_id: str = uuid.uuid4().hex
        self._ws_url: str = ""
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._current_prompt_id: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_server_url(self, base_url: str) -> None:
        """Derive WebSocket URL from the HTTP base URL."""
        url = base_url.rstrip("/")
        url = url.replace("https://", "wss://").replace("http://", "ws://")
        self._ws_url = f"{url}/ws?clientId={self.client_id}"

    def start(self) -> None:
        """Begin the persistent connection loop (call from async context via ensure_future)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._run_loop())

    def stop(self) -> None:
        """Gracefully stop the connection loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        delay_index = 0
        while self._running:
            try:
                async with websockets.connect(
                    self._ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    self.connected.emit()
                    delay_index = 0
                    await self._listen(ws)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.disconnected.emit()
                if not self._running:
                    break
                self.connection_error.emit(str(exc))
                delay = _RECONNECT_DELAYS[min(delay_index, len(_RECONNECT_DELAYS) - 1)]
                delay_index += 1
                await asyncio.sleep(delay)

        self.disconnected.emit()

    async def _listen(self, ws) -> None:
        async for raw in ws:
            if not self._running:
                break
            try:
                if isinstance(raw, str):
                    self._handle_json(json.loads(raw))
                elif isinstance(raw, bytes):
                    self._handle_binary(raw)
            except Exception:
                pass  # never crash the loop on a bad message

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _handle_json(self, msg: dict) -> None:
        msg_type: str = msg.get("type", "")
        data: dict = msg.get("data", {})

        if msg_type == "status":
            queue_rem = data.get("status", {}).get("exec_info", {}).get("queue_remaining", 0)
            self.queue_status_changed.emit(queue_rem)

        elif msg_type == "execution_start":
            pid = data.get("prompt_id", "")
            self._current_prompt_id = pid
            self.execution_started.emit(pid)

        elif msg_type == "execution_cached":
            pid = data.get("prompt_id", "")
            nodes = data.get("nodes", [])
            self.execution_cached.emit(pid, nodes)

        elif msg_type == "executing":
            pid = data.get("prompt_id", self._current_prompt_id)
            node = data.get("node")
            if node is None:
                # null node = all done
                self.execution_finished.emit(pid)
            else:
                self.node_executing.emit(pid, str(node))

        elif msg_type == "executed":
            pid = data.get("prompt_id", self._current_prompt_id)
            node = str(data.get("node", ""))
            output = data.get("output", {})
            self.node_executed.emit(pid, node, output)

        elif msg_type == "progress":
            pid = data.get("prompt_id", self._current_prompt_id)
            value = int(data.get("value", 0))
            maximum = int(data.get("max", 1))
            node = str(data.get("node", ""))
            self.progress.emit(pid, value, maximum, node)

        elif msg_type == "execution_error":
            pid = data.get("prompt_id", self._current_prompt_id)
            msg_text = data.get("exception_message", "Unknown error")
            self.execution_error.emit(pid, msg_text)

        elif msg_type == "execution_interrupted":
            pid = data.get("prompt_id", self._current_prompt_id)
            self.execution_interrupted.emit(pid)

    def _handle_binary(self, data: bytes) -> None:
        """Handle binary WebSocket frames (live preview images)."""
        if len(data) < 4:
            return
        event_type = struct.unpack(">I", data[:4])[0]

        if event_type == 1:
            # PREVIEW_IMAGE: 4-byte image-type header + raw bytes
            if len(data) < 8:
                return
            image_bytes = data[8:]
            pixmap = bytes_to_pixmap(image_bytes)
            if not pixmap.isNull():
                self.preview_image.emit(self._current_prompt_id, pixmap)

        elif event_type == 2:
            # PREVIEW_IMAGE_WITH_METADATA: 4-byte metadata length, JSON, image bytes
            if len(data) < 8:
                return
            meta_len = struct.unpack(">I", data[4:8])[0]
            image_bytes = data[8 + meta_len:]
            pixmap = bytes_to_pixmap(image_bytes)
            if not pixmap.isNull():
                self.preview_image.emit(self._current_prompt_id, pixmap)
