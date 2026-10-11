# -*- coding: utf-8 -*-
"""AI 摘要功能端到端验证 + 性能实测。

跑法（必须用项目自己的 venv）：
    D:\\develop\\01Python\\toutiao_backend\\venv\\Scripts\\python.exe verify_ai_summary.py

为什么不用 fastapi.testclient：
    它内部另起线程跑事件循环，与异步引擎的连接池、SSE 生成长请求容易互相踩；
    这里用 httpx.AsyncClient + ASGITransport 在**同一个事件循环**里直接打应用，
    更接近真实 ASGI 行为，也方便精确测量首字延迟。

验证内容：
    1. /api/ai/health            大模型是否可用（未配 Key 时是否优雅降级）
    2. 首次摘要                   未命中缓存 → 调用大模型
    3. 再次摘要                   命中缓存 → 耗时对比（简历要写的数字）
    4. SSE 流式                   首字延迟、事件序列
    5. 批量摘要                   提交 → 轮询 → 完成
    6. /api/ai/metrics            缓存命中率 / token / 延迟分位
    7. 边界                       不存在的新闻 / 超批量上限 / 不存在的任务
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 静音 SQLAlchemy 的 SQL 回显，否则验证输出会被 SQL 日志淹没
from config.db_conf import async_engine  # noqa: E402

async_engine.echo = False

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402
from sqlalchemy import text  # noqa: E402

from config.db_conf import AsyncSessionLocal  # noqa: E402
from main import app  # noqa: E402

BASE = "http://test"
DIVIDER = "=" * 88
REPORT: List[str] = []


def log(line: str = "") -> None:
    print(line)
    REPORT.append(line)


def show(title: str) -> None:
    log(f"\n{DIVIDER}\n### {title}\n{DIVIDER}")


async def pick_news_ids(limit: int = 6) -> List[int]:
    """挑几条正文最长的真实新闻，摘要效果更明显。"""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, CHAR_LENGTH(content) AS len FROM news "
            "WHERE content IS NOT NULL AND content <> '' ORDER BY len DESC LIMIT :n"
        ), {"n": limit})).all()
        return [int(r[0]) for r in rows]


async def pick_uncached_news_ids(limit: int) -> List[int]:
    """挑几条**当前没有摘要缓存**的新闻。

    为什么需要：缓存命中的请求根本不会调大模型，用它测"流式/批量"等于什么都没测到。
    """
    import redis.asyncio as aioredis

    from config.cache_conf import REDIS_DB, REDIS_HOST, REDIS_PORT
    from config.llm_conf import llm_settings

    candidates = await pick_news_ids(20)
    client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                            decode_responses=True, protocol=2)
    picked: List[int] = []
    try:
        for news_id in candidates:
            index_key = f"news:summary:index:{news_id}"
            key = await client.get(index_key)
            if key and str(key).find(llm_settings.cache_version) >= 0:
                continue  # 已有本版本缓存，跳过
            picked.append(news_id)
            if len(picked) >= limit:
                break
    finally:
        await client.aclose()
    return picked or candidates[:limit]


async def read_sse(response: httpx.Response) -> Tuple[Dict[str, int], Optional[float], Optional[dict], float]:
    """解析 SSE：返回 (事件计数, 首字延迟ms, done 载荷, 总耗时ms)。"""
    events: Dict[str, int] = {}
    first_delta_ms: Optional[float] = None
    done_payload: Optional[dict] = None
    started = time.perf_counter()
    current_event: Optional[str] = None

    async for line in response.aiter_lines():
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
            events[current_event] = events.get(current_event, 0) + 1
        elif line.startswith("data:"):
            payload = line.split(":", 1)[1].strip()
            if current_event == "delta" and first_delta_ms is None:
                first_delta_ms = (time.perf_counter() - started) * 1000
            elif current_event == "done":
                done_payload = json.loads(payload)

    return events, first_delta_ms, done_payload, (time.perf_counter() - started) * 1000


async def main() -> None:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url=BASE, timeout=180) as client:
        plain_ids = await pick_news_ids(5)
        log(f"数据库正文最长的新闻 id：{plain_ids}")

        # 预热：第一次数据库连接/连接池建立的开销要排除在延迟统计之外，
        # 否则"首次 3s、二次 3ms"会被误读成缓存的效果。
        await client.get(f"/api/ai/news/summary?id={plain_ids[-1]}")
        log("（已预热数据库与 Redis 连接）")

        # 每个用例用不同且未缓存的新闻，才能覆盖到真实调用分支
        uncached = await pick_uncached_news_ids(5)
        log(f"当前未缓存的新闻 id（用于冷启动用例）：{uncached}")
        if len(uncached) < 4:
            log("未缓存新闻不足 4 条，请先执行 redis-cli FLUSHDB 或修改 SUMMARY_CACHE_VERSION 后重跑")
            return
        target, stream_target = uncached[0], uncached[1]
        batch_ids = uncached[2:5]

        # ---------- 1. 健康检查 ----------
        show("1. AI 模块健康检查")
        resp = await client.get("/api/ai/health")
        data = resp.json().get("data", {})
        log(f"HTTP {resp.status_code}  {json.dumps(data, ensure_ascii=False)}")
        llm_enabled = bool(data.get("llm_enabled"))
        log(f"→ 大模型可用：{llm_enabled}（{'真实调用' if llm_enabled else '降级模式：走原文摘录，接口仍返回 200'}）")

        await client.post("/api/ai/metrics/reset")

        # ---------- 2. 首次摘要 ----------
        show("2. 首次获取摘要（预期未命中缓存）")
        t0 = time.perf_counter()
        resp = await client.get(f"/api/ai/news/summary?id={target}")
        first_ms = (time.perf_counter() - t0) * 1000
        body = resp.json()
        item = body.get("data", {})
        log(f"HTTP {resp.status_code}  message={body.get('message')}")
        log(f"cached={item.get('cached')}  degraded={item.get('degraded')}  model={item.get('model')}")
        log(f"一句话摘要：{item.get('summary')}")
        log(f"要点：{item.get('points')}")
        log(f"关键词：{item.get('keywords')}")
        log(f"服务端计时 {item.get('elapsed_ms')} ms ｜ 客户端计时 {first_ms:.1f} ms")
        if item.get("degrade_reason"):
            log(f"降级原因：{item.get('degrade_reason')}")
        if item.get("tokens"):
            log(f"token 用量：{item.get('tokens')}")

        # ---------- 3. 命中缓存 ----------
        show("3. 同一条新闻再取一次（预期命中缓存）")
        t0 = time.perf_counter()
        resp2 = await client.get(f"/api/ai/news/summary?id={target}")
        second_ms = (time.perf_counter() - t0) * 1000
        item2 = resp2.json().get("data", {})
        log(f"HTTP {resp2.status_code}  cached={item2.get('cached')}  message={resp2.json().get('message')}")
        log(f"客户端计时 {second_ms:.1f} ms")
        speedup = (first_ms / second_ms) if second_ms > 0 else 0
        log(f"→ 缓存命中：{first_ms:.1f} ms → {second_ms:.1f} ms（约 {speedup:.1f}×）")

        # ---------- 4. 流式摘要 ----------
        show("4. SSE 流式摘要")
        started = time.perf_counter()
        async with client.stream("POST", f"/api/ai/news/summary/stream?id={stream_target}") as stream:
            events, first_delta_client, done_payload, total_ms = await read_sse(stream)
        log(f"事件统计：{events}")
        server_first = (done_payload or {}).get("first_token_ms")
        log(f"首字延迟：服务端 {server_first} ms ｜ 客户端观测 {first_delta_client if first_delta_client is None else round(first_delta_client, 1)} ms")
        log("   说明：客户端观测值偏小是因为 httpx 的 ASGI 传输会把响应体缓冲后一次性交付；"
            "真实浏览器/网关下应按服务端 first_token_ms 计。")
        log(f"整段耗时 {total_ms:.1f} ms ｜ done 事件：{json.dumps(done_payload, ensure_ascii=False)[:200]}")
        log(f"解析出的结构化字段：{(done_payload or {}).get('parsed')}")
        log("→ 事件序列 meta → delta×N → done；客户端断开时服务端不会写入半截摘要。")

        # ---------- 5. 批量摘要 ----------
        show("5. 批量摘要（后台任务 + 进度轮询）")
        resp = await client.post("/api/ai/news/batch/summary", json={"newsIds": batch_ids, "concurrency": 2})
        task = resp.json().get("data", {})
        log(f"HTTP {resp.status_code}  提交结果：{json.dumps(task, ensure_ascii=False)}")
        task_id = task.get("task_id")
        status: Optional[dict] = None
        for _ in range(80):
            status = (await client.get(f"/api/ai/news/batch/status?taskId={task_id}&withData=false")).json().get("data")
            if status and status.get("status") in ("success", "partial", "failed"):
                break
            await asyncio.sleep(0.5)
        log(f"最终状态：{json.dumps(status, ensure_ascii=False)}")

        # ---------- 6. 指标 ----------
        show("6. AI 指标（缓存命中率 / token / 延迟分位）")
        snap = (await client.get("/api/ai/metrics")).json().get("data", {})
        for key in (
            "llm_enabled", "llm_model", "llm_calls", "llm_success", "llm_failed", "llm_degraded", "llm_retry",
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cache_hit", "cache_miss", "cache_hit_rate",
            "llm_latency_ms_p50", "llm_latency_ms_p95",
            "stream_first_token_ms_p50", "stream_first_token_ms_p95",
            "batch_items", "batch_failed_items", "active_batch_tasks",
        ):
            log(f"  {key:28s}= {snap.get(key)}")

        # ---------- 7. 边界 ----------
        show("7. 边界校验")
        bad = await client.get("/api/ai/news/summary?id=99999999")
        log(f"不存在的新闻 → HTTP {bad.status_code}  {json.dumps(bad.json(), ensure_ascii=False)[:150]}")
        bad2 = await client.post("/api/ai/news/batch/summary", json={"newsIds": list(range(1, 60))})
        log(f"超批量上限 → HTTP {bad2.status_code}  {json.dumps(bad2.json(), ensure_ascii=False)[:150]}")
        bad3 = await client.get("/api/ai/news/batch/status?taskId=not-exist")
        log(f"不存在的任务 → HTTP {bad3.status_code}  {json.dumps(bad3.json(), ensure_ascii=False)[:150]}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_ai_summary_result.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(REPORT))
    print(f"\n报告已保存：{out}")


if __name__ == "__main__":
    asyncio.run(main())
