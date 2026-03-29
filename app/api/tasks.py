from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.agent import AgentRunner
from app.auth import get_current_user
from app.config import settings
from app.models import Task, User
from app.shared import cancel_events

router = APIRouter(prefix="/task", tags=["tasks"])


@router.get("/demo-key", include_in_schema=False)
async def demo_key():
    if not settings.dev_mode:
        raise HTTPException(status_code=404, detail="Not available")
    return {"api_key": settings.demo_api_key}


from pydantic import field_validator

class TaskCreate(BaseModel):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def check_prompt_length(cls, v):
        if len(v.strip()) < 3:
            raise ValueError("Prompt too short")
        if len(v) > 10000:
            raise ValueError("Prompt too long (max 10000 chars)")
        return v.strip()


class TaskContinue(BaseModel):
    message: str


@router.post("", status_code=202)
async def create_task(
    body: TaskCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    if not user.has_budget:
        raise HTTPException(
            status_code=402,
            detail="Quota exhausted. Add your own OpenAI API key in Settings to continue.",
        )

    task = Task(user_id=user.id, prompt=body.prompt)
    await task.insert()

    runner = AgentRunner(task, user)
    background_tasks.add_task(runner.run)

    return {"task_id": task.task_id}


@router.post("/{task_id}/continue", status_code=202)
async def continue_task(
    task_id: str,
    body: TaskContinue,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    task = await Task.find_one(
        Task.task_id == task_id,
        Task.user_id == user.id,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in ("running", "pending"):
        raise HTTPException(
            status_code=409,
            detail="Task is still running. Use the chat to reply while it's active.",
        )
    if task.status == "paused":
        # Paused = waiting for user input — send via HITL instead
        from app.shared import hitl_events, hitl_responses
        hitl_responses[task_id] = body.message
        event = hitl_events.get(task_id)
        if event:
            event.set()
        return {"task_id": task.task_id, "status": "resumed"}
    if not task.messages:
        # Fallback: use original prompt as history
        task.messages = [{"role": "user", "content": task.prompt}]

    runner = AgentRunner(task, user, follow_up=body.message)
    background_tasks.add_task(runner.run)

    return {"task_id": task.task_id, "status": "continuing"}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    user: User = Depends(get_current_user),
):
    task = await Task.find_one(
        Task.task_id == task_id,
        Task.user_id == user.id,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("running", "pending", "paused"):
        raise HTTPException(status_code=409, detail="Task is not running")

    evt = cancel_events.get(task_id)
    if evt:
        evt.set()
    return {"task_id": task_id, "status": "cancelling"}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
):
    task = await Task.find_one(
        Task.task_id == task_id,
        Task.user_id == user.id,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Build chat history: user prompts/follow-ups only (agent responses come from result_data)
    chat_messages = []
    seen_prompt = False
    for m in (task.messages or []):
        role = m.get("role")
        content = m.get("content", "")
        if role != "user" or not isinstance(content, str) or not content.strip():
            continue
        # Skip system-injected / internal messages
        if content.startswith(("The task has timed out", "The user has cancelled", "You have reached the maximum", "[screenshot pruned", "Here is the current browser")):
            continue
        # Skip the original prompt (already in task.prompt) — only include follow-ups
        if not seen_prompt:
            seen_prompt = True
            continue
        chat_messages.append({"role": "user", "content": content})

    return {
        "task_id": task.task_id,
        "prompt": task.prompt,
        "status": task.status,
        "logs": task.logs,
        "result_data": task.result_data,
        "chat_messages": chat_messages,
        "has_history": bool(task.messages),
        "created_at": task.created_at.isoformat(),
    }


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    user: User = Depends(get_current_user),
):
    task = await Task.find_one(
        Task.task_id == task_id,
        Task.user_id == user.id,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Only block delete if task is actually running in this process
    if task.status in ("running", "pending") and task.task_id in cancel_events:
        raise HTTPException(status_code=409, detail="Cannot delete a running task — stop it first")
    # Stale running tasks (server restarted) can be deleted — fix status first
    if task.status in ("running", "pending", "paused"):
        task.status = "failed"
        task.logs.append("Task orphaned (server restarted). Marked as failed.")
        await task.save()
    await task.delete()
    return {"deleted": task_id}


@router.get("")
async def list_tasks(
    user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 10,
):
    query = Task.find(Task.user_id == user.id)
    total = await query.count()
    tasks = (
        await query
        .sort(-Task.created_at)
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    def _slim_result(rd):
        """Strip heavy fields (screenshots, history) from result_data for list view."""
        if not rd:
            return rd
        return {k: v for k, v in rd.items() if k not in ("screenshots", "history")}

    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "status": t.status,
                "prompt": t.prompt[:80],
                "result_data": _slim_result(t.result_data),
                "created_at": t.created_at.isoformat(),
            }
            for t in tasks
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }
