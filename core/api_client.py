from __future__ import annotations

from typing import Any, Optional
import httpx

from core.exceptions import ComfyUIError, ComfyUIConnectionError


class ComfyUIClient:
    """Async HTTP client wrapping the ComfyUI REST API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8188") -> None:
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def open(self) -> None:
        """Create the underlying HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _check_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise ComfyUIConnectionError("HTTP client not opened. Call open() first.")
        return self._client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, **params) -> Any:
        client = self._check_client()
        try:
            resp = await client.get(path, params=params or None)
        except httpx.ConnectError as exc:
            raise ComfyUIConnectionError(f"Cannot reach {self.base_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ComfyUIConnectionError(f"Request timed out: {exc}") from exc
        _raise_for_status(resp)
        return resp.json()

    async def _get_bytes(self, path: str, **params) -> bytes:
        client = self._check_client()
        try:
            resp = await client.get(path, params=params or None)
        except httpx.ConnectError as exc:
            raise ComfyUIConnectionError(f"Cannot reach {self.base_url}: {exc}") from exc
        _raise_for_status(resp)
        return resp.content

    async def _post(self, path: str, body: dict) -> Any:
        client = self._check_client()
        try:
            resp = await client.post(path, json=body)
        except httpx.ConnectError as exc:
            raise ComfyUIConnectionError(f"Cannot reach {self.base_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ComfyUIConnectionError(f"Request timed out: {exc}") from exc
        _raise_for_status(resp)
        # Some endpoints return empty bodies on success
        if resp.content:
            return resp.json()
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect_test(self) -> dict:
        """Ping the server via GET /system_stats. Returns the stats dict."""
        return await self._get("/system_stats")

    async def get_object_info(self, node_class: str = "") -> dict:
        """Return the full object_info schema, or just one node class."""
        path = f"/object_info/{node_class}" if node_class else "/object_info"
        return await self._get(path)

    async def get_models(self, folder: str) -> list[str]:
        """List model filenames in a given folder (checkpoints, loras, vae …)."""
        return await self._get(f"/models/{folder}")

    async def post_prompt(self, workflow: dict, client_id: str) -> dict:
        """Submit a workflow for execution. Returns {prompt_id, number, node_errors}."""
        body = {
            "prompt": workflow,
            "client_id": client_id,
            "extra_data": {"extra_pnginfo": {"workflow": workflow}},
        }
        result = await self._post("/prompt", body)
        if "error" in result:
            err = result["error"]
            raise ComfyUIError(
                err.get("message", "Unknown error"),
                detail=err.get("details", ""),
            )
        return result

    async def get_queue(self) -> dict:
        """Return {queue_running: [...], queue_pending: [...]}."""
        return await self._get("/queue")

    async def get_history(self, max_items: int = 50, offset: int = 0) -> dict:
        """Return history dict keyed by prompt_id."""
        return await self._get("/history", max_items=max_items, offset=offset)

    async def get_history_item(self, prompt_id: str) -> dict:
        """Return history for a single prompt_id."""
        data = await self._get(f"/history/{prompt_id}")
        return data.get(prompt_id, {})

    async def get_image_bytes(
        self, filename: str, subfolder: str = "", image_type: str = "output"
    ) -> bytes:
        """Download a generated image as raw bytes."""
        return await self._get_bytes(
            "/view", filename=filename, subfolder=subfolder, type=image_type
        )

    async def interrupt(self, prompt_id: str = "") -> None:
        """Interrupt the current (or specific) running prompt."""
        body: dict = {}
        if prompt_id:
            body["prompt_id"] = prompt_id
        await self._post("/interrupt", body)

    async def delete_queue_items(self, prompt_ids: list[str]) -> None:
        """Remove specific pending items from the queue."""
        await self._post("/queue", {"delete": prompt_ids})

    async def clear_queue(self) -> None:
        """Clear all pending queue items."""
        await self._post("/queue", {"clear": True})

    async def clear_history(self) -> None:
        """Clear generation history."""
        await self._post("/history", {"clear": True})

    async def free_memory(self, unload_models: bool = True) -> None:
        """Free VRAM / unload models."""
        await self._post("/free", {"unload_models": unload_models, "free_memory": True})


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise ComfyUIError(
            f"HTTP {resp.status_code}",
            status_code=resp.status_code,
            detail=str(detail),
        )
