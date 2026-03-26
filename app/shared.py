"""
Shared in-process state for HITL coordination and WebSocket messaging.
All values are keyed by task_id (str).
"""
import asyncio
from typing import Dict

# Fired by the agent loop when human input has been submitted
hitl_events: Dict[str, asyncio.Event] = {}

# Stores the human text response for each paused task
hitl_responses: Dict[str, str] = {}

# Screenshot + reason sent to the frontend when a task pauses for HITL
hitl_data: Dict[str, dict] = {}

# Per-task asyncio.Queue used to push messages to the WebSocket handler
ws_queues: Dict[str, asyncio.Queue] = {}
