"""AI 摘要接口：流式、非流式、批量后台任务、指标。

接口清单：
    GET  /api/ai/news/summary?id=1        非流式摘要（JSON，带 cached / elapsed_ms / tokens）
    POST /api/ai/news/summary/stream      流式摘要（SSE：meta → delta* → done）
    POST /api/ai/news/batch/summary       批量摘要（立即返回 task_id，后台生成）
    GET  /api/ai/news/batch/status        查询批量任务进度
    GET  /api/ai/metrics                  可观测性指标（缓存命中率 / token / 延迟分位）
    POST /api/ai/metrics/reset            清空指标（压测前调用）
"""

from __future__ import annotations

import asyncio
import traceback

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.db_conf import AsyncSessionLocal, get_db
from config.llm_conf import llm_settings
from schemas.ai import BatchSummaryRequest
from services import metrics, summary_service, task_registry
from services import llm_service

router = APIRouter(prefix="/api/ai", tags=["ai"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Nginx 反代下必须关闭缓冲，否则流式会被攒成一坨再返回
    "X-Accel-Buffering": "no",
}


def _ok(message: str, data=None, **extra):
    return JSONResponse(content={"code": 200, "message": message, "data": data, **extra})


# ---------------------------------------------------------------------------
# 非流式摘要
# ---------------------------------------------------------------------------
@router.get("/news/summary", summary="获取新闻 AI 摘要（非流式）")
async def get_news_summary(
    news_id: int = Query(..., alias="id", description="新闻 id"),
    use_cache: bool = Query(True, alias="useCache", description="是否使用缓存"),
    db: AsyncSession = Depends(get_db),
):
    payload, hit = await summary_service.get_summary(db, news_id, use_cache=use_cache)
    if payload is None:
        raise HTTPException(status_code=404, detail="新闻不存在")

    return _ok(
        "命中缓存" if hit else ("大模型降级摘要" if payload.get("degraded") else "AI 摘要生成成功"),
        payload,
        cached=bool(hit),
        degraded=bool(payload.get("degraded")),
    )


# ---------------------------------------------------------------------------
# 流式摘要（SSE）
# ---------------------------------------------------------------------------
@router.post("/news/summary/stream", summary="获取新闻 AI 摘要（SSE 流式）")
async def stream_news_summary(
    news_id: int = Query(..., alias="id", description="新闻 id"),
    db: AsyncSession = Depends(get_db),
):
    # 流开始前先校验新闻存在，避免用 SSE 事件回报 404 让前端解析麻烦
    news = await summary_service.load_news(db, news_id)
    if news is None:
        raise HTTPException(status_code=404, detail="新闻不存在")

    return StreamingResponse(
        summary_service.stream_summary(db, news_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ---------------------------------------------------------------------------
# 批量摘要（后台任务）
# ---------------------------------------------------------------------------
async def _run_batch_task(task_id: str, news_ids: list[int], concurrency: int | None, use_cache: bool) -> None:
    """后台任务：自己开数据库会话（请求级会话此时已经关闭）。"""
    await task_registry.update_task(task_id, status=task_registry.STATUS_RUNNING)
    try:
        async with AsyncSessionLocal() as db:  # 独立会话，不依赖请求生命周期
            result = await summary_service.batch_get_summaries(
                db, news_ids, concurrency=concurrency, use_cache=use_cache
            )
        status = (
            task_registry.STATUS_SUCCESS
            if not result["failed_ids"]
            else (task_registry.STATUS_FAILED if result["success"] == 0 else task_registry.STATUS_PARTIAL)
        )
        await task_registry.update_task(
            task_id,
            status=status,
            finished=result["success"],
            failed_ids=result["failed_ids"],
            elapsed_ms=result["elapsed_ms"],
            data=result,
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务失败必须落进任务状态，不能只打日志
        await task_registry.update_task(
            task_id,
            status=task_registry.STATUS_FAILED,
            error=str(exc),
            traceback=traceback.format_exc()[-800:],
        )
    finally:
        await task_registry.cleanup_expired()


@router.post("/news/batch/summary", summary="批量生成 AI 摘要（异步任务）")
async def batch_summary(
    background_tasks: BackgroundTasks,
    payload: BatchSummaryRequest = Body(...),
):
    news_ids = payload.newsIds
    if len(news_ids) > llm_settings.batch_max_items:
        raise HTTPException(
            status_code=400,
            detail=f"单批最多 {llm_settings.batch_max_items} 条，当前 {len(news_ids)} 条",
        )

    task_id = await task_registry.create_task(total=len(news_ids))
    background_tasks.add_task(
        _run_batch_task,
        task_id,
        news_ids,
        payload.concurrency,
        payload.useCache and not payload.forceRefresh,
    )

    return _ok(
        "批量任务已提交",
        {"task_id": task_id, "status": task_registry.STATUS_PENDING, "total": len(news_ids)},
        task_id=task_id,
    )


@router.get("/news/batch/status", summary="查询批量摘要任务进度")
async def batch_status(
    task_id: str = Query(..., alias="taskId"),
    with_data: bool = Query(True, alias="withData", description="是否返回摘要内容"),
):
    task = await task_registry.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    data = task.get("data")
    if data and not with_data:
        data = {k: v for k, v in data.items() if k != "items"}

    return _ok("查询成功", {
        "task_id": task["task_id"],
        "status": task["status"],
        "total": task["total"],
        "finished": task["finished"],
        "failed_ids": task["failed_ids"],
        "elapsed_ms": task["elapsed_ms"],
        "error": task.get("error"),
        "data": data,
    })


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
@router.get("/metrics", summary="AI 功能指标（缓存命中率 / token / 延迟分位）")
async def get_metrics():
    snapshot = await metrics.snapshot()
    snapshot["llm_enabled"] = llm_service.is_llm_enabled()
    snapshot["llm_model"] = llm_settings.model
    snapshot["cache_expire_seconds"] = llm_settings.cache_expire
    snapshot["cache_version"] = llm_settings.cache_version
    snapshot["active_batch_tasks"] = len(task_registry.all_task_ids())
    return _ok("获取指标成功", snapshot)


@router.post("/metrics/reset", summary="清空 AI 指标（压测前调用）")
async def reset_metrics():
    await metrics.reset()
    return _ok("指标已清空", None)


@router.get("/health", summary="AI 模块健康检查")
async def ai_health():
    """反映大模型是否可用，便于前端决定是否展示"AI 摘要"入口。"""
    return _ok("AI 模块状态", {
        "llm_enabled": llm_service.is_llm_enabled(),
        "model": llm_settings.model,
        "base_url": llm_settings.base_url,
        "mode": "llm" if llm_service.is_llm_enabled() else "degraded(未配置 LLM_API_KEY)",
    })
