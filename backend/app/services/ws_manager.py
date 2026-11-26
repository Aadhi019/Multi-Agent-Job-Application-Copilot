from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from fastapi import WebSocket


class RunProgressManager:
    """Thread-safe WebSocket manager streaming live LangGraph & agent progress events."""

    def __init__(self, history_limit: int = 100) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=history_limit)
        )
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self._connections[run_id].add(websocket)
            history = list(self._history.get(run_id, ()))

        for event in history:
            await websocket.send_json(event)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        with self._lock:
            conns = self._connections.get(run_id)
            if conns and websocket in conns:
                conns.remove(websocket)

    async def _broadcast_async(self, channel: str, payload: dict[str, Any]) -> None:
        with self._lock:
            targets = list(self._connections.get(channel, ()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            with self._lock:
                for ws in dead:
                    self._connections[channel].discard(ws)

    def emit_sync(
        self,
        *,
        run_id: str,
        agent_name: str,
        step: str,
        status: str,
        message: str,
    ) -> dict[str, Any]:
        """Record a progress event and push it to subscribers of run_id and 'global'."""
        event = {
            "run_id": run_id,
            "agent_name": agent_name,
            "step": step,
            "status": status,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._history[run_id].append(event)
            if run_id != "global":
                self._history["global"].append(event)

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast_async(run_id, event), self._loop)
            if run_id != "global":
                asyncio.run_coroutine_threadsafe(self._broadcast_async("global", event), self._loop)

        return event

    def get_history(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history.get(run_id, ()))


ws_manager = RunProgressManager()
