from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy,
)

from models.job import Job, JobStatus


_STATUS_COLORS = {
    JobStatus.PENDING:    "#888888",
    JobStatus.RUNNING:    "#f0c040",
    JobStatus.COMPLETED:  "#44cc44",
    JobStatus.FAILED:     "#ee4444",
    JobStatus.CANCELLED:  "#888888",
}

_STATUS_LABELS = {
    JobStatus.PENDING:    "Pending",
    JobStatus.RUNNING:    "Running",
    JobStatus.COMPLETED:  "Done",
    JobStatus.FAILED:     "Failed",
    JobStatus.CANCELLED:  "Cancelled",
}

_COL_ID       = 0
_COL_STATUS   = 1
_COL_LORA     = 2   # LoRA name (populated only for multi-LoRA runs)
_COL_PROGRESS = 3
_COL_DURATION = 4
_COL_ACTION   = 5


class QueuePanel(QWidget):
    """Displays all jobs (pending, running, completed, failed) in a table."""

    view_job_requested  = Signal(str)   # prompt_id — open images in viewer
    cancel_job_requested = Signal(str)  # prompt_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._jobs: dict[str, Job] = {}  # prompt_id -> Job
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Header row: summary (left) + Clear Done (right)
        header_row = QHBoxLayout()
        self._summary_label = QLabel("No jobs yet", self)
        self._summary_label.setStyleSheet(
            "QLabel { font-size: 13px; font-weight: bold; padding: 2px 4px; }"
        )
        self._summary_label.setWordWrap(False)
        header_row.addWidget(self._summary_label, stretch=1)
        self._clear_btn = QPushButton("Clear Done", self)
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.clicked.connect(self._clear_completed)
        header_row.addWidget(self._clear_btn)
        layout.addLayout(header_row)

        # Refresh timer — keeps the "running" ETA ticking every second
        self._summary_timer = QTimer(self)
        self._summary_timer.setInterval(1000)
        self._summary_timer.timeout.connect(self._update_summary)

        self._table = QTableWidget(0, 6, self)
        self._table.setHorizontalHeaderLabels(["ID", "Status", "LoRA", "Progress", "Time", ""])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # LoRA fills remaining space
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 70)
        self._table.setColumnWidth(1, 62)
        self._table.setColumnWidth(3, 52)
        self._table.setColumnWidth(4, 58)
        self._table.setColumnWidth(5, 70)
        hdr.setMinimumSectionSize(40)
        hdr.setStretchLastSection(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add_job(self, job: Job) -> None:
        self._jobs[job.prompt_id] = job
        self._insert_row(job)
        self._update_summary()

    def update_job(self, job: Job) -> None:
        self._jobs[job.prompt_id] = job
        row = self._find_row(job.prompt_id)
        if row >= 0:
            self._update_row(row, job)
        self._update_summary()

    def get_job(self, prompt_id: str) -> Job | None:
        return self._jobs.get(prompt_id)

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _insert_row(self, job: Job) -> None:
        row = 0  # insert at top
        self._table.insertRow(row)
        self._table.setItem(row, _COL_ID, QTableWidgetItem(job.display_id))

        status_item = QTableWidgetItem(_STATUS_LABELS[job.status])
        status_item.setForeground(QColor(_STATUS_COLORS[job.status]))
        self._table.setItem(row, _COL_STATUS, status_item)

        # LoRA column — show shortened filename (strip path & extension) or em-dash
        lora_display = ""
        if job.lora_name:
            import os as _os
            lora_display = _os.path.splitext(_os.path.basename(job.lora_name))[0]
        lora_item = QTableWidgetItem(lora_display or "—")
        lora_item.setToolTip(job.lora_name or "")
        self._table.setItem(row, _COL_LORA, lora_item)

        self._table.setItem(row, _COL_PROGRESS, QTableWidgetItem("0%"))
        self._table.setItem(row, _COL_DURATION, QTableWidgetItem(""))

        # Store prompt_id in the ID cell for retrieval
        self._table.item(row, _COL_ID).setData(Qt.ItemDataRole.UserRole, job.prompt_id)

        # Action button
        btn = QPushButton("Cancel", self._table)
        btn.setFixedHeight(22)
        btn.clicked.connect(lambda _, pid=job.prompt_id: self.cancel_job_requested.emit(pid))
        self._table.setCellWidget(row, _COL_ACTION, btn)
        self._table.setRowHeight(row, 26)

    def _update_row(self, row: int, job: Job) -> None:
        status_item = self._table.item(row, _COL_STATUS)
        if status_item:
            status_item.setText(_STATUS_LABELS[job.status])
            status_item.setForeground(QColor(_STATUS_COLORS[job.status]))

        prog_item = self._table.item(row, _COL_PROGRESS)
        if prog_item:
            prog_item.setText(f"{job.progress_pct}%")

        dur_item = self._table.item(row, _COL_DURATION)
        if dur_item:
            dur_item.setText(job.duration_str)

        # Update action button
        btn = self._table.cellWidget(row, _COL_ACTION)
        if isinstance(btn, QPushButton):
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                btn.setText("View")
                try:
                    btn.clicked.disconnect()
                except Exception:
                    pass
                btn.clicked.connect(lambda _, pid=job.prompt_id: self.view_job_requested.emit(pid))
            elif job.status == JobStatus.RUNNING:
                btn.setText("Cancel")

    def _find_row(self, prompt_id: str) -> int:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_ID)
            if item and item.data(Qt.ItemDataRole.UserRole) == prompt_id:
                return row
        return -1

    def _clear_completed(self) -> None:
        rows_to_remove = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_ID)
            if not item:
                continue
            pid = item.data(Qt.ItemDataRole.UserRole)
            job = self._jobs.get(pid)
            if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                rows_to_remove.append(row)
        for row in reversed(rows_to_remove):
            self._table.removeRow(row)
        self._update_summary()

    # ------------------------------------------------------------------
    # Summary bar
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_seconds(secs: float) -> str:
        """Format a duration in seconds to a compact human-readable string."""
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        m, s = divmod(secs, 60)
        if m < 60:
            return f"{m}m {s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m"

    def _update_summary(self) -> None:
        jobs = list(self._jobs.values())
        total    = len(jobs)
        pending  = sum(1 for j in jobs if j.status == JobStatus.PENDING)
        running  = sum(1 for j in jobs if j.status == JobStatus.RUNNING)
        done     = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
        failed   = sum(1 for j in jobs if j.status in (JobStatus.FAILED, JobStatus.CANCELLED))

        if total == 0:
            self._summary_label.setText("No jobs yet")
            self._summary_timer.stop()
            return

        parts: list[str] = []

        # Counts
        count_parts = [f"{total} job{'s' if total != 1 else ''}"]
        if pending:
            count_parts.append(f"{pending} queued")
        if running:
            count_parts.append(f"{running} running")
        if done:
            count_parts.append(f"{done} done")
        if failed:
            count_parts.append(f"{failed} failed")
        parts.append("  ".join(count_parts))

        # Average gen time from completed jobs (for queue ETA)
        gen_times = [j.gen_time for j in jobs if j.gen_time is not None]
        avg_gen = sum(gen_times) / len(gen_times) if gen_times else None

        # Current job ETA
        current_remaining: float | None = None
        running_jobs = [j for j in jobs if j.status == JobStatus.RUNNING]
        if running_jobs:
            rj = running_jobs[0]
            if rj.started_at and rj.progress_value > 0 and rj.progress_max > 0:
                elapsed = (datetime.now() - rj.started_at).total_seconds()
                remaining_steps = rj.progress_max - rj.progress_value
                current_remaining = elapsed * remaining_steps / rj.progress_value
                parts.append(f"current: ~{self._fmt_seconds(current_remaining)}")
            elif avg_gen is not None:
                # No progress yet — use average
                if rj.started_at:
                    elapsed = (datetime.now() - rj.started_at).total_seconds()
                    current_remaining = max(0.0, avg_gen - elapsed)
                    parts.append(f"current: ~{self._fmt_seconds(current_remaining)}")

        # Queue completion ETA (pending jobs after the current one finishes)
        if pending > 0 and avg_gen is not None:
            queue_eta = (current_remaining if current_remaining is not None else 0.0)
            queue_eta += pending * avg_gen
            parts.append(f"queue done: ~{self._fmt_seconds(queue_eta)}")
        elif pending > 0:
            parts.append(f"{pending} pending")

        self._summary_label.setText("  •  ".join(parts))

        # Keep ticking while something is running
        if running:
            if not self._summary_timer.isActive():
                self._summary_timer.start()
        else:
            self._summary_timer.stop()

    def _on_row_double_clicked(self, index) -> None:
        item = self._table.item(index.row(), _COL_ID)
        if item:
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid:
                self.view_job_requested.emit(pid)
