"""批量摘要任务注册表（进程内）。

为什么需要它：大模型单条摘要要几秒，一批 30 条不可能让前端 HTTP 请求一直等着。
所以 POST 立刻返回 task_id，真正的生成放到后台任务里跑，前端轮询 /batch/status 拿进度。

生产环境应该换成 Celery / ARQ + Redis 队列（多进程、可重试、能持久化）；
这里用进程内字典，是为了在"不加中间件"的前提下把**异步任务 + 进度查询**的完整链路跑通，
并把接口契约设计成与真实队列一致（task_id + 状态查询），未来替换实现不影响前端。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from config.llm_conf import llm_settings

_lock = asyncio.Lock()
_tasks: Dict[str, Dict[str, Any]] = {}

# 任务状态：pending（已创建）→ running（生成中）→ success / partial / failed
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"


async def create_task(total: int) -> str:
    task_id = uuid.uuid4().hex
    async with _lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "status": STATUS_PENDING,
            "total": total,
            "finished": 0,
            "failed_ids": [],
            "elapsed_ms": 0.0,
            "created_at": time.time(),
            "data": None,
        }
    return task_id


async def update_task(task_id: str, **fields: Any) -> None:
    async with _lock:
        if task_id in _tasks:
            _tasks[task_id].update(fields)


async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    async with _lock:
        task = _tasks.get(task_id)
        return dict(task) if task else None


async def cleanup_expired() -> int:
    """清理超期任务，避免进程内字典无限增长（后台任务里定期调用）。"""
    deadline = time.time() - llm_settings.task_expire
    async with _lock:
        expired = [tid for tid, task in _tasks.items() if task.get("created_at", 0) < deadline]
        for tid in expired:
            _tasks.pop(tid, None)
    return len(expired)


def all_task_ids() -> List[str]:
    return list(_tasks.keys())
