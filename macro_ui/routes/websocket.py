from __future__ import annotations
import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agora_ui.live_world import get_pixel_live_store



router = APIRouter()

MACRO_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = MACRO_PACKAGE_ROOT.parent

class PixelLiveWebSocketManager:
    def __init__(self, package_root: Path) -> None:
        self.package_root = Path(package_root).resolve()
        self._connections: dict[str, dict[str, set[WebSocket]]] = {}
        self._lock = asyncio.Lock()
        self._tick_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop(), name="pixel-live-ws-tick")
        self._flush_task = asyncio.create_task(self._flush_loop(), name="pixel-live-ws-flush")

    async def stop(self) -> None:
        self._running = False
        tasks = [task for task in (self._tick_task, self._flush_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            connections = self._connections
            self._connections = {}
        for sessions in connections.values():
            for sockets in sessions.values():
                for socket in list(sockets):
                    try:
                        await socket.close(code=1001)
                    except Exception:
                        continue

    async def connect(self, *, access_code: str, session_id: str, websocket: WebSocket) -> dict[str, Any]:
        store = get_pixel_live_store(str(self.package_root), access_code)
        welcome = await asyncio.to_thread(store.realtime_session_bootstrap, session_id)
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "hello",
                "access_code": access_code,
                "session_id": session_id,
                **welcome,
            }
        )
        async with self._lock:
            session_map = self._connections.setdefault(access_code, {})
            sockets = session_map.setdefault(session_id, set())
            sockets.add(websocket)
        return welcome

    async def disconnect(self, *, access_code: str, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            session_map = self._connections.get(access_code, {})
            sockets = session_map.get(session_id, set())
            sockets.discard(websocket)
            if not sockets:
                session_map.pop(session_id, None)
            if not session_map:
                self._connections.pop(access_code, None)

    async def handle_message(self, *, access_code: str, session_id: str, websocket: WebSocket, payload: dict[str, Any]) -> None:
        store = get_pixel_live_store(str(self.package_root), access_code)
        message_type = str(payload.get("type", payload.get("message_type", "input"))).strip().lower() or "input"
        if message_type in {"ping", "heartbeat"}:
            await asyncio.to_thread(store.touch_realtime_session, session_id)
            await websocket.send_json(
                {
                    "type": "pong",
                    "access_code": access_code,
                    "session_id": session_id,
                    "server_time_ms": int(round(time.time() * 1000.0)),
                }
            )
            return
        if message_type in {"input", "move"}:
            queued = await asyncio.to_thread(store.enqueue_realtime_input, session_id, payload)
            await websocket.send_json(
                {
                    "type": "input_queued",
                    "access_code": access_code,
                    **queued,
                }
            )
            return
        if message_type == "action":
            action_payload = dict(payload.get("payload", {})) if isinstance(payload.get("payload"), dict) else dict(payload)
            action_payload["session_id"] = session_id
            result = await asyncio.to_thread(store.submit_action, session_id, action_payload)
            await websocket.send_json(
                {
                    "type": "action_result",
                    "access_code": access_code,
                    "session_id": session_id,
                    **result,
                }
            )
            return
        await websocket.send_json(
            {
                "type": "error",
                "access_code": access_code,
                "session_id": session_id,
                "detail": f"unsupported websocket message type: {message_type}",
            }
        )

    async def _tick_loop(self) -> None:
        import queue
        while self._running:
            started_at = time.perf_counter()
            access_codes = await self._active_access_codes()
            for access_code in access_codes:
                store = get_pixel_live_store(str(self.package_root), access_code)
                delta = await asyncio.to_thread(store.process_realtime_tick)
                if delta:
                    await self._broadcast_access_code(access_code, delta)
                if hasattr(store, "_pending_broadcasts"):
                    while not store._pending_broadcasts.empty():
                        try:
                            broadcast = store._pending_broadcasts.get_nowait()
                            await self._broadcast_access_code(access_code, broadcast)
                        except queue.Empty:
                            break
                        except Exception as exc:
                            print(f"[WS_BROADCAST_ERROR] {exc}")
                            break
            elapsed = time.perf_counter() - started_at
            await asyncio.sleep(max(0.005, 0.05 - elapsed))

    async def _flush_loop(self) -> None:
        while self._running:
            access_codes = await self._active_access_codes()
            for access_code in access_codes:
                store = get_pixel_live_store(str(self.package_root), access_code)
                await asyncio.to_thread(store.flush_hot_spatial_state, force=False)
            await asyncio.sleep(1.0)

    async def _active_access_codes(self) -> list[str]:
        async with self._lock:
            return [access_code for access_code, session_map in self._connections.items() if session_map]

    async def _broadcast_access_code(self, access_code: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            session_map = self._connections.get(access_code, {})
            targets = [
                (session_id, socket)
                for session_id, sockets in session_map.items()
                for socket in list(sockets)
            ]
        stale: list[tuple[str, WebSocket]] = []
        for session_id, socket in targets:
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append((session_id, socket))
        for session_id, socket in stale:
            await self.disconnect(access_code=access_code, session_id=session_id, websocket=socket)


@router.websocket("/api/pixel/worlds/{access_code}/live/ws/{session_id}")
async def api_live_ws(access_code: str, session_id: str, websocket: WebSocket) -> None:
    from fastapi import Request
    from macro_ui.routes.pixel_api import _canonical_pixel_world_record
    # Note: access app via websocket.app
    app = websocket.app
    normalized = str(access_code).strip()
    normalized_session_id = str(session_id).strip()
    if not normalized_session_id:
        await websocket.close(code=4400)
        return
    if _canonical_pixel_world_record(normalized) is None:
        await websocket.close(code=4404)
        return
    manager = getattr(app.state, "live_ws_manager", None)
    if manager is None:
        await websocket.close(code=1011)
        return
    try:
        await manager.connect(access_code=normalized, session_id=normalized_session_id, websocket=websocket)
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                await websocket.send_json({"type": "error", "detail": "websocket payload must be a JSON object"})
                continue
            await manager.handle_message(
                access_code=normalized,
                session_id=normalized_session_id,
                websocket=websocket,
                payload=payload,
            )
    except WebSocketDisconnect:
        pass
    except FileNotFoundError:
        try:
            await websocket.close(code=4404)
        except Exception:
            pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await manager.disconnect(access_code=normalized, session_id=normalized_session_id, websocket=websocket)
