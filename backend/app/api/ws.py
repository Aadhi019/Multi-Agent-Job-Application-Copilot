from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ws_manager import ws_manager

router = APIRouter(tags=["websocket"])


async def _handle_run_ws(websocket: WebSocket, run_id: str) -> None:
    await ws_manager.connect(run_id, websocket)
    try:
        while True:
            # Keep connection open and handle optional client pings
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "pong", "run_id": run_id})
    except WebSocketDisconnect:
        ws_manager.disconnect(run_id, websocket)


@router.websocket("/ws/runs/{run_id}")
async def ws_run_progress_root(websocket: WebSocket, run_id: str) -> None:
    """Stream live agent progress events for a run_id (or 'global')."""
    await _handle_run_ws(websocket, run_id)


@router.websocket("/api/ws/runs/{run_id}")
async def ws_run_progress_api(websocket: WebSocket, run_id: str) -> None:
    """Alias under /api/ws/runs/{run_id} for proxied frontend clients."""
    await _handle_run_ws(websocket, run_id)
