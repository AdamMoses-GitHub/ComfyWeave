from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QDockWidget, QStatusBar, QMessageBox, QLabel, QApplication,
)

from core.api_client import ComfyUIClient
from core.websocket_client import WebSocketClient
from core.workflow import WorkflowManager
from core.exceptions import ComfyUIError, ComfyUIConnectionError
from models.config_model import AppConfig
from models.job import Job, JobStatus, ImageRef
from utils.config_manager import ConfigManager
from utils.image_utils import bytes_to_pixmap

from ui.connection_bar import ConnectionBar
from ui.workflow_panel import WorkflowPanel
from ui.progress_bar import GenerationProgressBar
from ui.queue_panel import QueuePanel
from ui.image_viewer import ImageViewer, _ImageMeta
from ui.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self, config_manager: ConfigManager) -> None:
        super().__init__()
        self._cfg_mgr = config_manager
        self._cfg = config_manager.config

        self._api: Optional[ComfyUIClient] = None
        self._ws = WebSocketClient(self)
        self._jobs: dict[str, Job] = {}

        self.setWindowTitle("ComfyWeave — ComfyUI Client")
        self._restore_geometry()
        self._build_ui()
        self._build_menus()
        self._connect_signals()

        # Restore last workflow silently before connecting — forms will appear
        # immediately; server-side options (LoRA lists etc.) fill in once connected.
        if self._cfg.last_workflow_path:
            self._workflow_panel.load_from_path(self._cfg.last_workflow_path)

        if self._cfg.auto_connect:
            asyncio.ensure_future(self._do_connect(self._cfg.server_url))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Connection bar (full width at top)
        self._conn_bar = ConnectionBar(self)
        self._conn_bar.set_url(self._cfg.server_url)
        root.addWidget(self._conn_bar)

        # Horizontal splitter: left panel | image viewer
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left panel
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._workflow_panel = WorkflowPanel(self._cfg_mgr, left_panel)
        left_layout.addWidget(self._workflow_panel, stretch=1)

        self._progress_bar = GenerationProgressBar(left_panel)
        left_layout.addWidget(self._progress_bar)

        self._splitter.addWidget(left_panel)

        # Right panel — image viewer
        self._image_viewer = ImageViewer(self._cfg_mgr, self)
        self._splitter.addWidget(self._image_viewer)
        self._splitter.setSizes([self._cfg.splitter_left_width,
                                  self._cfg.window_width - self._cfg.splitter_left_width])
        root.addWidget(self._splitter, stretch=1)

        # Queue dock (bottom)
        self._queue_panel = QueuePanel(self)
        queue_dock = QDockWidget("Generation Queue", self)
        queue_dock.setObjectName("queue_dock")
        queue_dock.setWidget(self._queue_panel)
        queue_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, queue_dock)
        self._queue_panel.setMinimumHeight(80)
        queue_dock.setMinimumHeight(100)

        # Status bar
        self._status_label = QLabel("Not connected", self)
        self._queue_label = QLabel("Queue: 0", self)
        self.statusBar().addWidget(self._status_label, 1)
        self.statusBar().addPermanentWidget(self._queue_label)

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        load_act = QAction("&Load Workflow…", self)
        load_act.setShortcut("Ctrl+O")
        load_act.triggered.connect(self._workflow_panel._on_load)
        file_menu.addAction(load_act)
        file_menu.addSeparator()
        settings_act = QAction("&Settings…", self)
        settings_act.setShortcut("Ctrl+,")
        settings_act.triggered.connect(self._open_settings)
        file_menu.addAction(settings_act)
        file_menu.addSeparator()
        exit_act = QAction("E&xit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # Generation
        gen_menu = mb.addMenu("&Generation")
        self._interrupt_act = QAction("&Interrupt Current", self)
        self._interrupt_act.setShortcut("Ctrl+.")
        self._interrupt_act.triggered.connect(self._on_interrupt)
        self._interrupt_act.setEnabled(False)
        gen_menu.addAction(self._interrupt_act)
        free_act = QAction("Free &VRAM", self)
        free_act.triggered.connect(self._on_free_vram)
        gen_menu.addAction(free_act)

        # Help
        help_menu = mb.addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _connect_signals(self) -> None:
        # Connection bar
        self._conn_bar.connect_requested.connect(
            lambda url: asyncio.ensure_future(self._do_connect(url))
        )
        self._conn_bar.disconnect_requested.connect(self._do_disconnect)

        # Workflow panel
        self._workflow_panel.generate_requested.connect(
            lambda overrides, path, batch, dims: asyncio.ensure_future(
                self._do_generate(overrides, path, batch, dims)
            )
        )
        self._workflow_panel.stop_current_requested.connect(
            lambda: asyncio.ensure_future(self._do_stop_current())
        )
        self._workflow_panel.clear_queue_requested.connect(
            lambda: asyncio.ensure_future(self._do_clear_queue())
        )
        self._workflow_panel.stop_and_clear_requested.connect(
            lambda: asyncio.ensure_future(self._do_stop_and_clear())
        )
        self._workflow_panel.retry_last_requested.connect(
            lambda: asyncio.ensure_future(self._do_retry_last())
        )

        # WebSocket → progress bar
        self._ws.progress.connect(self._progress_bar.on_progress)
        self._ws.node_executing.connect(self._progress_bar.on_node_executing)
        self._ws.execution_started.connect(self._progress_bar.on_execution_started)
        self._ws.execution_finished.connect(self._progress_bar.on_execution_finished)
        self._ws.execution_error.connect(self._progress_bar.on_execution_error)

        # WebSocket → job state management
        self._ws.execution_started.connect(self._on_ws_execution_started)
        self._ws.execution_finished.connect(self._on_ws_execution_finished)
        self._ws.execution_error.connect(self._on_ws_execution_error)
        self._ws.execution_interrupted.connect(self._on_ws_interrupted)
        self._ws.progress.connect(self._on_ws_progress)
        self._ws.preview_image.connect(self._image_viewer.show_preview)
        self._ws.queue_status_changed.connect(self._on_queue_status_changed)

        # Image viewer → workflow panel
        self._image_viewer.load_workflow_requested.connect(self._on_load_workflow_from_image)

        # WebSocket connection state
        self._ws.connected.connect(self._on_ws_connected)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.connection_error.connect(self._on_ws_error)

        # Queue panel
        self._queue_panel.cancel_job_requested.connect(
            lambda pid: asyncio.ensure_future(self._do_cancel(pid))
        )
        self._queue_panel.view_job_requested.connect(
            lambda pid: asyncio.ensure_future(self._load_job_images(pid))
        )

        # Workflow panel refresh button
        self._workflow_panel.refresh_models_requested.connect(
            lambda: asyncio.ensure_future(self._fetch_server_options())
        )

    # ------------------------------------------------------------------
    # Async operations
    # ------------------------------------------------------------------

    async def _do_connect(self, url: str) -> None:
        self._conn_bar.set_connecting()
        self._status_label.setText("Connecting…")
        try:
            self._api = ComfyUIClient(url)
            await self._api.open()
            stats = await self._api.connect_test()
            self._conn_bar.set_connected()
            self._conn_bar.set_server_info(stats)
            self._status_label.setText("Connected")
            self._cfg_mgr.update(server_url=url)

            # Start WebSocket
            self._ws.set_server_url(url)
            self._ws.start()

            self._workflow_panel.set_connected(True)
            # Fetch available models / samplers in the background
            asyncio.ensure_future(self._fetch_server_options())
            self._update_control_buttons()
        except ComfyUIConnectionError as exc:
            self._conn_bar.set_disconnected(str(exc))
            self._status_label.setText(f"Error: {exc}")
            self._workflow_panel.set_connected(False)
            self._api = None
        except Exception as exc:
            self._conn_bar.set_disconnected(str(exc))
            self._status_label.setText(f"Error: {exc}")
            self._workflow_panel.set_connected(False)
            self._api = None

    def _do_disconnect(self) -> None:
        self._ws.stop()
        if self._api:
            asyncio.ensure_future(self._api.close())
            self._api = None
        self._conn_bar.set_disconnected()
        self._status_label.setText("Disconnected")
        self._workflow_panel.set_connected(False)
        self._update_control_buttons()

    async def _fetch_server_options(self) -> None:
        """Fetch available models and sampler/scheduler lists from the server.

        Builds a dict mapping ComfyUI input names to lists of valid choices,
        then pushes it to the workflow panel so combo boxes are populated.
        """
        if not self._api:
            return
        self._status_label.setText("Fetching model lists…")
        options: dict[str, list[str]] = {}

        # Model folders → input name mapping
        folder_map = {
            "loras":          "lora_name",
            "checkpoints":    "ckpt_name",
            "vae":            "vae_name",
            "upscale_models": "model_name",
            "controlnet":     "control_net_name",
            "style_models":   "style_model_name",
        }
        for folder, input_name in folder_map.items():
            try:
                files = await self._api.get_models(folder)
                if isinstance(files, list) and files:
                    options[input_name] = sorted(files, key=str.lower)
            except Exception:
                pass  # folder may not exist on this ComfyUI instance

        # Samplers and schedulers come from object_info/KSampler
        try:
            info = await self._api.get_object_info("KSampler")
            ksampler = info.get("KSampler", {})
            required = ksampler.get("input", {}).get("required", {})
            for field in ("sampler_name", "scheduler"):
                combo_values = required.get(field, [[]])[0]
                if isinstance(combo_values, list) and combo_values:
                    options[field] = combo_values
        except Exception:
            pass

        self._workflow_panel.set_server_options(options)

        # Build a summary for the status bar
        summaries = []
        for folder, input_name in folder_map.items():
            if input_name in options:
                summaries.append(f"{len(options[input_name])} {folder}")
        self._status_label.setText(
            "Models loaded: " + ", ".join(summaries) if summaries else "Connected (no models found)"
        )

    async def _do_generate(
        self,
        overrides: dict,
        workflow_path: str,
        batch_count: int = 1,
        dims: list[list[dict]] | None = None,
    ) -> None:
        if not self._api:
            QMessageBox.warning(self, "Not Connected", "Connect to a ComfyUI server first.")
            return

        manager = self._workflow_panel.get_workflow_manager()
        if not manager.is_loaded:
            QMessageBox.warning(self, "No Workflow", "Load a workflow JSON file first.")
            return

        import itertools as _itertools
        import random as _random
        import copy as _copy
        import uuid as _uuid

        def _reseed(ovr: dict) -> dict:
            """Deep-copy *ovr* and replace every 'seed' with a fresh random int."""
            result = _copy.deepcopy(ovr)
            for node_inputs in result.values():
                if isinstance(node_inputs, dict) and "seed" in node_inputs:
                    node_inputs["seed"] = _random.randint(0, 2_147_483_647)
            return result

        # Build Cartesian product across all active dims.
        # Each dim is a list of node-patch dicts: {node_id: {input_name: value}}.
        # When no dims are active, produce a single empty combo.
        active_dims = dims or []
        combos = list(_itertools.product(*active_dims)) if active_dims else [()]

        for combo in combos:
            # All batch iterations of one Cartesian combo share a colour group.
            group_id = str(_uuid.uuid4())

            # Merge all patches in this combo on top of the base overrides.
            merged = _copy.deepcopy(overrides)
            for patch in combo:
                for node_id, node_patch in patch.items():
                    merged.setdefault(node_id, {}).update(node_patch)

            # Derive a display label from the first lora_name found in merged inputs.
            lora_label = next(
                (v.get("lora_name", "") for v in merged.values()
                 if isinstance(v, dict) and "lora_name" in v),
                "",
            )

            for i in range(batch_count):
                run_overrides = merged if i == 0 else _reseed(_copy.deepcopy(merged))

                try:
                    workflow = manager.apply_overrides(run_overrides)
                    result = await self._api.post_prompt(workflow, self._ws.client_id)
                    prompt_id: str = result["prompt_id"]

                    job = Job(
                        prompt_id=prompt_id,
                        client_id=self._ws.client_id,
                        workflow_snapshot=workflow,
                        workflow_path=workflow_path,
                        lora_name=lora_label,
                        generation_group_id=group_id,
                    )
                    self._jobs[prompt_id] = job
                    self._queue_panel.add_job(job)
                    self._interrupt_act.setEnabled(True)
                    self._update_control_buttons()
                except ComfyUIError as exc:
                    QMessageBox.critical(self, "Generation Error", str(exc))
                    return
                except Exception as exc:
                    QMessageBox.critical(self, "Unexpected Error", str(exc))
                    return

    # ------------------------------------------------------------------
    # Control operations (stop / clear / retry)
    # ------------------------------------------------------------------

    async def _do_stop_current(self) -> None:
        """Interrupt the actively running generation."""
        if not self._api:
            return
        try:
            await self._api.interrupt()
            self._status_label.setText("Generation interrupted")
        except Exception as exc:
            self._status_label.setText(f"Stop error: {exc}")

    async def _do_clear_queue(self) -> None:
        """Delete all pending (not running) jobs from the server queue."""
        if not self._api:
            return
        try:
            await self._api.clear_queue()
            # Mark every local PENDING job as cancelled
            for job in self._jobs.values():
                if job.status == JobStatus.PENDING:
                    job.status = JobStatus.CANCELLED
                    self._queue_panel.update_job(job)
            self._status_label.setText("Queue cleared")
            self._update_control_buttons()
        except Exception as exc:
            self._status_label.setText(f"Clear queue error: {exc}")

    async def _do_stop_and_clear(self) -> None:
        """Interrupt current job and clear all pending jobs."""
        if not self._api:
            return
        try:
            await self._api.interrupt()
            await self._api.clear_queue()
            for job in self._jobs.values():
                if job.status in (JobStatus.RUNNING, JobStatus.PENDING):
                    job.status = JobStatus.CANCELLED
                    job.completed_at = datetime.now()
                    self._queue_panel.update_job(job)
            self._status_label.setText("Stopped and queue cleared")
            self._update_control_buttons()
        except Exception as exc:
            self._status_label.setText(f"Stop & clear error: {exc}")

    async def _do_retry_last(self) -> None:
        """Re-submit the most recently finished job with its original workflow snapshot."""
        if not self._api:
            return
        # Find the most recent non-pending job that has a workflow snapshot
        last_job = None
        for job in reversed(list(self._jobs.values())):
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED) \
                    and job.workflow_snapshot:
                last_job = job
                break
        if not last_job:
            self._status_label.setText("No previous job to retry")
            return
        try:
            result = await self._api.post_prompt(
                last_job.workflow_snapshot, self._ws.client_id
            )
            prompt_id: str = result["prompt_id"]
            new_job = Job(
                prompt_id=prompt_id,
                client_id=self._ws.client_id,
                workflow_snapshot=last_job.workflow_snapshot,
                workflow_path=last_job.workflow_path,
                lora_name=last_job.lora_name,
            )
            self._jobs[prompt_id] = new_job
            self._queue_panel.add_job(new_job)
            self._status_label.setText(f"Retrying {last_job.display_id}…")
            self._update_control_buttons()
        except ComfyUIError as exc:
            self._status_label.setText(f"Retry error: {exc}")
        except Exception as exc:
            self._status_label.setText(f"Retry error: {exc}")

    def _update_control_buttons(self) -> None:
        """Push current job-state snapshot to WorkflowPanel control buttons."""
        connected = self._api is not None
        has_running = any(j.status == JobStatus.RUNNING  for j in self._jobs.values())
        has_pending = any(j.status == JobStatus.PENDING  for j in self._jobs.values())
        has_any     = bool(self._jobs)
        self._workflow_panel.set_control_state(has_running, has_pending, has_any, connected)

    async def _do_cancel(self, prompt_id: str) -> None:
        if not self._api:
            return
        job = self._jobs.get(prompt_id)
        try:
            if job and job.status == JobStatus.RUNNING:
                await self._api.interrupt(prompt_id)
            else:
                await self._api.delete_queue_items([prompt_id])
            if job:
                job.status = JobStatus.CANCELLED
                self._queue_panel.update_job(job)
        except Exception as exc:
            self._status_label.setText(f"Cancel error: {exc}")

    async def _load_job_images(self, prompt_id: str) -> None:
        if not self._api:
            return
        job = self._jobs.get(prompt_id)
        if not job:
            return
        if not job.output_images:
            # Try to fetch from history
            try:
                item = await self._api.get_history_item(prompt_id)
                outputs = item.get("outputs", {})
                for node_id, node_out in outputs.items():
                    for img in node_out.get("images", []):
                        job.output_images.append(
                            ImageRef(img["filename"], img.get("subfolder", ""), img.get("type", "output"))
                        )
            except Exception:
                pass

        self._image_viewer.clear()
        for ref in job.output_images:
            try:
                data = await self._api.get_image_bytes(ref.filename, ref.subfolder, ref.type)
                px = bytes_to_pixmap(data)
                if not px.isNull():
                    import os as _os
                    _meta = _ImageMeta(
                        filename=ref.filename,
                        width=px.width(),
                        height=px.height(),
                        lora_name=job.lora_name,
                        workflow_name=_os.path.basename(job.workflow_path),
                        created_at=job.created_at.strftime("%Y-%m-%d %H:%M"),
                        prompt_id_short=job.prompt_id[:8],
                    )
                    self._image_viewer.add_image(
                        px, ref.filename,
                        generation_id=job.generation_group_id or job.prompt_id,
                        meta=_meta,
                        raw_bytes=data,
                    )
            except Exception:
                pass

    async def _on_free_vram(self) -> None:
        if self._api:
            try:
                await self._api.free_memory()
                self._status_label.setText("VRAM freed")
            except Exception as exc:
                self._status_label.setText(f"Free VRAM error: {exc}")

    # ------------------------------------------------------------------
    # WebSocket signal handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_ws_execution_started(self, prompt_id: str) -> None:
        job = self._jobs.get(prompt_id)
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now()
            self._queue_panel.update_job(job)
        self._update_control_buttons()

    @Slot(str)
    def _on_ws_execution_finished(self, prompt_id: str) -> None:
        job = self._jobs.get(prompt_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.progress_value = job.progress_max
            self._queue_panel.update_job(job)
            self._interrupt_act.setEnabled(False)
            asyncio.ensure_future(self._fetch_and_show_images(prompt_id))
        self._update_control_buttons()

    @Slot(str, str)
    def _on_ws_execution_error(self, prompt_id: str, message: str) -> None:
        job = self._jobs.get(prompt_id)
        if job:
            job.status = JobStatus.FAILED
            job.error_message = message
            job.completed_at = datetime.now()
            self._queue_panel.update_job(job)
        self._interrupt_act.setEnabled(False)
        self._status_label.setText(f"Error: {message[:80]}")
        self._update_control_buttons()

    @Slot(str)
    def _on_ws_interrupted(self, prompt_id: str) -> None:
        job = self._jobs.get(prompt_id)
        if job:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now()
            self._queue_panel.update_job(job)
        self._interrupt_act.setEnabled(False)
        self._update_control_buttons()

    @Slot(str, int, int, str)
    def _on_ws_progress(self, prompt_id: str, value: int, maximum: int, node_id: str) -> None:
        job = self._jobs.get(prompt_id)
        if job:
            job.progress_value = value
            job.progress_max = maximum
            job.current_node = node_id
            self._queue_panel.update_job(job)

    @Slot(int)
    def _on_queue_status_changed(self, remaining: int) -> None:
        self._queue_label.setText(f"Queue: {remaining}")

    @Slot()
    def _on_ws_connected(self) -> None:
        pass  # Connection bar already updated via REST connect

    @Slot()
    def _on_ws_disconnected(self) -> None:
        self._status_label.setText("WebSocket disconnected — reconnecting…")

    @Slot(str)
    def _on_ws_error(self, error: str) -> None:
        self._status_label.setText(f"WS error: {error[:80]}")

    # ------------------------------------------------------------------
    # Image fetching after completion
    # ------------------------------------------------------------------

    async def _fetch_and_show_images(self, prompt_id: str) -> None:
        if not self._api:
            return
        job = self._jobs.get(prompt_id)
        if not job:
            return
        gen_time = job.gen_time  # computed from started_at / completed_at
        try:
            item = await self._api.get_history_item(prompt_id)
            outputs = item.get("outputs", {})
            images_found: list = []
            for node_id, node_out in outputs.items():
                for img_ref in node_out.get("images", []):
                    images_found.append(img_ref)
            # Distribute gen_time equally across all output images so each thumb
            # shows the same generation time (most workflows produce one image).
            for img_ref in images_found:
                ref = ImageRef(
                    img_ref["filename"],
                    img_ref.get("subfolder", ""),
                    img_ref.get("type", "output"),
                )
                job.output_images.append(ref)
                try:
                    data = await self._api.get_image_bytes(ref.filename, ref.subfolder, ref.type)
                    px = bytes_to_pixmap(data)
                    if not px.isNull():
                        import os as _os
                        _meta = _ImageMeta(
                            filename=ref.filename,
                            width=px.width(),
                            height=px.height(),
                            gen_time=gen_time,
                            lora_name=job.lora_name,
                            workflow_name=_os.path.basename(job.workflow_path),
                            created_at=job.created_at.strftime("%Y-%m-%d %H:%M"),
                            prompt_id_short=job.prompt_id[:8],
                        )
                        self._image_viewer.add_image(
                            px, ref.filename, gen_time,
                            generation_id=job.generation_group_id or prompt_id,
                            meta=_meta,
                            raw_bytes=data,
                        )
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Other slots / actions
    # ------------------------------------------------------------------

    def _on_interrupt(self) -> None:
        if self._api:
            asyncio.ensure_future(self._api.interrupt())

    def _on_load_workflow_from_image(self, raw: bytes) -> None:
        """Load the workflow embedded in a generated PNG into the workflow panel."""
        from PySide6.QtWidgets import QMessageBox
        ok = self._workflow_panel.load_from_png_bytes(raw)
        if not ok:
            QMessageBox.warning(
                self,
                "No Workflow Found",
                "No ComfyUI workflow metadata was found in this image.\n\n"
                "Only images generated by ComfyUI with 'Save Image' or by "
                "ComfyWeave contain embedded workflows.",
            )

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._cfg, self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._cfg_mgr.config = dlg.config
            self._cfg = dlg.config
            self._cfg_mgr.save()
            self._conn_bar.set_url(self._cfg.server_url)
            _apply_theme(self._cfg.theme)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About ComfyWeave",
            "<b>ComfyWeave</b><br>"
            "A PySide6 desktop client for ComfyUI.<br><br>"
            "Connect to any ComfyUI instance, load workflow JSON files,<br>"
            "and generate images with real-time progress tracking.",
        )

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        self.setGeometry(
            self._cfg.window_x,
            self._cfg.window_y,
            self._cfg.window_width,
            self._cfg.window_height,
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        geo = self.geometry()
        self._cfg_mgr.update(
            window_x=geo.x(),
            window_y=geo.y(),
            window_width=geo.width(),
            window_height=geo.height(),
            splitter_left_width=self._splitter.sizes()[0],
            batch_count=self._workflow_panel.get_batch_count(),
            workflow_overrides=self._workflow_panel.get_all_overrides(),
        )
        self._ws.stop()
        if self._api:
            asyncio.ensure_future(self._api.close())
        event.accept()


def _apply_theme(theme: str) -> None:
    from PySide6.QtGui import QPalette, QColor
    app = QApplication.instance()
    if not app:
        return
    if theme == "dark":
        app.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window,          QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.WindowText,      QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Base,            QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(40, 40, 40))
        palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(255, 255, 220))
        palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Text,            QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Button,          QColor(53, 53, 53))
        palette.setColor(QPalette.ColorRole.ButtonText,      QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.BrightText,      QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Link,            QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.Highlight,       QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        app.setPalette(palette)
    else:
        app.setStyle("Fusion")
        app.setPalette(QPalette())
