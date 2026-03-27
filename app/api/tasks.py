from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.agent import AgentRunner
from app.auth import get_current_user
from app.config import settings
from app.models import Task, User

router = APIRouter(prefix="/task", tags=["tasks"])


@router.get("/demo-key", include_in_schema=False)
async def demo_key():
    return {"api_key": settings.demo_api_key}


class TaskCreate(BaseModel):
    prompt: str


class TaskContinue(BaseModel):
    message: str


@router.post("", status_code=202)
async def create_task(
    body: TaskCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
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
    return {
        "task_id": task.task_id,
        "status": task.status,
        "logs": task.logs,
        "result_data": task.result_data,
        "has_history": bool(task.messages),
        "created_at": task.created_at.isoformat(),
    }


@router.get("")
async def list_tasks(
    user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 20,
):
    tasks = (
        await Task.find(Task.user_id == user.id)
        .sort(-Task.created_at)
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    return [
        {
            "task_id": t.task_id,
            "status": t.status,
            "prompt": t.prompt[:80],
            "result_data": t.result_data,
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
    ]
