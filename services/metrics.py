"""AI 功能可观测性指标（进程内单实例统计）。

面试点：接了大模型之后，"接口快了多少、省了多少 token"必须有数据支撑，
否则简历上只能写"接入了大模型"这种没有信息量的话。
这里用进程内计数器 + 滑动窗口记录，暴露 /api/ai/metrics 给前端/压测脚本读取。

注意：进程内统计在多 worker 部署下只反映单进程，生产应改用 Prometheus；
本项目的定位是"把指标暴露出来"，所以刻意保持零依赖。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Deque, Dict

_MAX_LATENCY_SAMPLES = 200
_lock = asyncio.Lock()

_stats: Dict[str, Any] = {
    # 大模型调用
    "llm_calls": 0,
    "llm_success": 0,
    "llm_failed": 0,
    "llm_degraded": 0,          # 未配置 Key / 调用失败后走降级回答的次数
    "llm_retry": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "llm_latency_ms": deque(maxlen=_MAX_LATENCY_SAMPLES),
    # 缓存
    "cache_hit": 0,
    "cache_miss": 0,
    # 流式
    "stream_requests": 0,
    "stream_first_token_ms": deque(maxlen=_MAX_LATENCY_SAMPLES),
    # 批量任务
    "batch_tasks": 0,
    "batch_items": 0,
    "batch_failed_items": 0,
}


def _percentile(samples: Deque[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * len(ordered) + 0.5)) - 1))
    return round(ordered[index], 2)


async def incr(name: str, delta: int = 1) -> None:
    async with _lock:
        _stats[name] = _stats.get(name, 0) + delta


async def observe_latency(name: str, elapsed_ms: float) -> None:
    async with _lock:
        bucket = _stats.get(name)
        if isinstance(bucket, deque):
            bucket.append(round(elapsed_ms, 2))


async def add_tokens(prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    async with _lock:
        _stats["prompt_tokens"] += max(0, prompt_tokens)
        _stats["completion_tokens"] += max(0, completion_tokens)
        _stats["total_tokens"] = _stats["prompt_tokens"] + _stats["completion_tokens"]


async def snapshot() -> Dict[str, Any]:
    """返回一份可直接 JSON 序列化的快照（含命中率、P50/P95）。"""
    async with _lock:
        data = {k: v for k, v in _stats.items() if not isinstance(v, deque)}
        llm_latency = list(_stats["llm_latency_ms"])
        first_token = list(_stats["stream_first_token_ms"])

    total_lookup = data["cache_hit"] + data["cache_miss"]
    data["cache_hit_rate"] = round(data["cache_hit"] / total_lookup, 4) if total_lookup else 0.0
    data["llm_success_rate"] = round(data["llm_success"] / data["llm_calls"], 4) if data["llm_calls"] else 0.0
    data["llm_latency_ms_p50"] = _percentile(deque(llm_latency), 50)
    data["llm_latency_ms_p95"] = _percentile(deque(llm_latency), 95)
    data["stream_first_token_ms_p50"] = _percentile(deque(first_token), 50)
    data["stream_first_token_ms_p95"] = _percentile(deque(first_token), 95)
    data["samples"] = {"llm_latency": len(llm_latency), "stream_first_token": len(first_token)}
    return data


async def reset() -> None:
    """清空统计（压测前调用，保证口径干净）。"""
    async with _lock:
        for key, value in list(_stats.items()):
            if isinstance(value, deque):
                value.clear()
            else:
                _stats[key] = 0


def now_ms() -> float:
    return time.perf_counter() * 1000
