"""
WebSocket endpoint: ws /ws/task/{task_id}

Responsibilities
----------------
1. Stream task logs and status updates to the browser in real-time.
2. Push HITL requests (screenshot + reason) to the operator when the
   agent loop pauses.
3. Receive operator responses and wake the paused agent loop.

Message protocol (JSON)
-----------------------
Server → Client:
  { "type": "status",       "status": "...", "logs": [...] }
  { "type": "log",          "message": "...", "status": "...", "logs": [...] }
  { "type": "hitl_request", "reason": "...", "screenshot_base64": "..." }
  { "type": "heartbeat" }

Client → Server:
  { "type": "hitl_response", "response": "..." }
"""
import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.models import Task
from app.shared import cancel_events, hitl_events, hitl_responses, ws_queues

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 15  # seconds
_STATUS_POLL_INTERVAL = 2  # seconds between DB polls when queue is empty


async def hitl_websocket(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue()
    ws_queues[task_id] = queue

    receive_task = asyncio.create_task(_receive_loop(websocket, task_id))
    send_task = asyncio.create_task(_send_loop(websocket, task_id, queue))

    # Run both coroutines; stop as soon as either ends (disconnect / task done)
    done, pending = await asyncio.wait(
        [receive_task, send_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    ws_queues.pop(task_id, None)


# ---------------------------------------------------------------------------
# Receive loop – handles operator messages
# ---------------------------------------------------------------------------

async def _receive_loop(websocket: WebSocket, task_id: str) -> None:
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "cancel":
                evt = cancel_events.get(task_id)
                if evt:
                    evt.set()
                    log.info("Cancel signal received for task %s", task_id)

            if msg.get("type") == "hitl_response":
                response_text = msg.get("response", "")
                hitl_responses[task_id] = response_text
                event = hitl_events.get(task_id)
                if event:
                    event.set()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("WS receive loop ended for task %s: %s", task_id, exc)


# ---------------------------------------------------------------------------
# Send loop – streams updates to the operator
# ---------------------------------------------------------------------------

async def _send_loop(
    websocket: WebSocket, task_id: str, queue: asyncio.Queue
) -> None:
    try:
        # Send current state immediately on connect
        task = await Task.find_one(Task.task_id == task_id)
        if task:
            await _send(websocket, {
                "type": "status",
                "status": task.status,
                "logs": task.logs,
            })
            if task.status in ("completed", "failed"):
                return

        elapsed = 0.0
        while True:
            try:
                update = await asyncio.wait_for(
                    queue.get(), timeout=_STATUS_POLL_INTERVAL
                )
                await _send(websocket, update)

                # Stop streaming once the task reaches a terminal state
                if update.get("type") == "status" and update.get("status") in (
                    "completed", "failed"
                ):
                    return

                elapsed = 0.0

            except asyncio.TimeoutError:
                # Heartbeat every _HEARTBEAT_INTERVAL seconds
                elapsed += _STATUS_POLL_INTERVAL
                if elapsed >= _HEARTBEAT_INTERVAL:
                    await _send(websocket, {"type": "heartbeat"})
                    elapsed = 0.0

                # Also poll DB so late-joining clients get current state
                task = await Task.find_one(Task.task_id == task_id)
                if task:
                    await _send(websocket, {
                        "type": "status",
                        "status": task.status,
                        "logs": task.logs,
                    })
                    if task.status in ("completed", "failed"):
                        return

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("WS send loop ended for task %s: %s", task_id, exc)


async def _send(websocket: WebSocket, payload: dict) -> None:
    try:
        await websocket.send_json(payload)
    except Exception:
        pass
