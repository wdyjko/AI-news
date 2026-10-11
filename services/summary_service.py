"""AI 摘要服务：缓存优先 → 大模型生成 → 失败降级，三层保障。

调用链（面试时按这个顺序讲）：
    1. 取新闻正文（走已有的新闻缓存 crud，不重复查库）
    2. **缓存优先**：按 news_id + 正文 hash 查 Redis 摘要缓存，命中直接返回（0 token、毫秒级）
    3. 未命中 → 截断正文后调用大模型（流式/非流式）
    4. **失败降级**：未配 Key / 超时 / 额度不足 → 用 description 或正文首段兜底，
       接口返回 200 + degraded 标记，绝不返回 5xx（"大模型挂了不能把新闻接口带崩"）
    5. 成功后写入 Redis 缓存，下次同内容直接命中

批量与流式都在这个模块里实现，路由层保持很薄。
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from cache.summary_cache import content_hash, get_cached_summary, set_cached_summary
from config.llm_conf import llm_settings
from crud import news_cache
from services import llm_service, metrics

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SUMMARY_SYSTEM_PROMPT = (
    "你是一个严谨的新闻摘要助手。你的输出必须完全基于用户提供的正文，"
    "禁止补充正文中没有的事实，禁止编造数字、机构名或时间。"
)

SUMMARY_PROMPT_TEMPLATE = """请为下面这条新闻生成摘要，严格按以下格式输出，不要输出多余内容：

【一句话摘要】
（不超过40字，点明核心事实）

【要点】
1. （不超过25字）
2. （不超过25字）
3. （不超过25字）

【关键词】
关键词1、关键词2、关键词3

新闻标题：{title}
新闻正文：
{content}
"""

FALLBACK_NOTICE = "（当前为大模型降级摘要：直接摘录原文，未做语义提炼）"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def build_prompt(title: str, content: str) -> str:
    """构造 Prompt：正文超长时截断，控制单次调用成本。"""
    text = (content or "").strip()
    limit = max(200, llm_settings.max_input_chars)
    truncated = len(text) > limit
    if truncated:
        text = text[:limit]
    prompt = SUMMARY_PROMPT_TEMPLATE.format(title=(title or "").strip(), content=text)
    if truncated:
        prompt += f"\n（注意：正文过长已截断，仅提供前 {limit} 字。）"
    return prompt


def _strip_markup(text: str) -> str:
    """去掉换行/多余空格，便于 stream 模式把整段摘要切片送出。"""
    return re.sub(r"\s+", " ", (text or "").strip())


def fallback_summary(title: str, description: Optional[str], content: str, reason: str) -> Dict[str, Any]:
    """降级摘要：只用原文信息，不编造。"""
    base = _strip_markup(description or "")
    if not base:
        body = _strip_markup(content or "")
        base = body[:80] + ("…" if len(body) > 80 else "")
    return {
        "summary": base or "（无可用正文）",
        "degraded": True,
        "degrade_reason": reason,
        "notice": FALLBACK_NOTICE,
        "model": llm_settings.model if llm_service.is_llm_enabled() else "",
        "source": "fallback",
    }


def parse_summary(text: str) -> Dict[str, Any]:
    """把模型输出解析成结构化字段（解析失败也不报错，原文照样返回）。"""
    cleaned = (text or "").strip()
    parsed: Dict[str, Any] = {"summary": "", "points": [], "keywords": []}

    one_line = re.search(r"【一句话摘要】\s*(.+?)(?:\n|【|$)", cleaned, re.S)
    if one_line:
        parsed["summary"] = _strip_markup(one_line.group(1))

    points_block = re.search(r"【要点】(.*?)(?:【|$)", cleaned, re.S)
    if points_block:
        for line in points_block.group(1).splitlines():
            matched = re.match(r"\s*\d+[.、)]\s*(.+)", line.strip())
            if matched and matched.group(1).strip():
                parsed["points"].append(_strip_markup(matched.group(1)))

    keywords_block = re.search(r"【关键词】\s*(.+?)(?:\n\n|$)", cleaned, re.S)
    if keywords_block:
        raw = keywords_block.group(1).replace("\n", " ")
        parsed["keywords"] = [k.strip() for k in re.split(r"[、,，\s]+", raw) if k.strip()][:8]

    if not parsed["summary"]:
        # 模型没按格式输出时，退化为第一段
        parsed["summary"] = _strip_markup(cleaned.split("\n")[0])[:80]
    return parsed


def _normalize_news(news: Any) -> Dict[str, Any]:
    """兼容 ORM 对象与缓存字典两种形态（news_cache 两个分支返回的类型不同）。"""
    if isinstance(news, dict):
        return {
            "id": news.get("id"),
            "title": news.get("title") or "",
            "description": news.get("description"),
            "content": news.get("content") or "",
        }
    return {
        "id": getattr(news, "id", None),
        "title": getattr(news, "title", "") or "",
        "description": getattr(news, "description", None),
        "content": getattr(news, "content", "") or "",
    }


async def load_news(db: AsyncSession, news_id: int) -> Optional[Dict[str, Any]]:
    news = await news_cache.get_news_detail(db, news_id)
    if not news:
        return None
    return _normalize_news(news)


# ---------------------------------------------------------------------------
# 单条摘要（非流式）
# ---------------------------------------------------------------------------
async def get_summary(db: AsyncSession, news_id: int, use_cache: bool = True) -> Tuple[Optional[Dict[str, Any]], int]:
    """返回 (摘要数据, 是否命中缓存)。新闻不存在时返回 (None, 0)。"""
    news = await load_news(db, news_id)
    if news is None:
        return None, 0

    digest = content_hash(news["title"] + news["content"])

    if use_cache:
        cached = await get_cached_summary(news_id, digest)
        if cached:
            await metrics.incr("cache_hit")
            cached = dict(cached)
            cached["cached"] = True
            return cached, 1
    await metrics.incr("cache_miss")

    started = metrics.now_ms()
    result = await llm_service.complete(
        build_prompt(news["title"], news["content"]),
        system=SUMMARY_SYSTEM_PROMPT,
    )
    elapsed = metrics.now_ms() - started
    await metrics.observe_latency("llm_latency_ms", elapsed)

    if result.degraded or not result.text:
        payload = fallback_summary(
            news["title"], news["description"], news["content"],
            result.degrade_reason or "大模型未返回内容",
        )
        payload.update({"news_id": news_id, "content_hash": digest, "cached": False,
                        "elapsed_ms": round(elapsed, 1)})
        if use_cache:
            # 降级结果也缓存（短 TTL）：否则大模型不可用期间，每个请求都会白跑一遍
            # 数据库 + 截断逻辑，前端列表页滚动时会把后端打满。
            await set_cached_summary(
                news_id, digest, payload, expire=llm_settings.degraded_cache_expire
            )
        return payload, 0

    payload = parse_summary(result.text)
    payload.update({
        "news_id": news_id,
        "content_hash": digest,
        "degraded": False,
        "degrade_reason": "",
        "notice": "",
        "model": result.model or llm_settings.model,
        "source": "llm",
        "cached": False,
        "elapsed_ms": round(elapsed, 1),
        "tokens": {
            "prompt": result.prompt_tokens,
            "completion": result.completion_tokens,
        },
    })
    await set_cached_summary(news_id, digest, payload)
    return payload, 0


# ---------------------------------------------------------------------------
# 单条摘要（SSE 流式）
# ---------------------------------------------------------------------------
def sse_event(event: str, data: Any) -> str:
    """构造一条 SSE 消息（data 用 JSON，前端按事件名分发）。"""
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _fake_stream(text: str, chunk_size: int = 12) -> List[str]:
    """缓存命中时无需再调模型，把整段摘要切片模拟流式，前端体验一致。"""
    cleaned = _strip_markup(text)
    return [cleaned[i:i + chunk_size] for i in range(0, len(cleaned), chunk_size)] or [cleaned]


async def stream_summary(db: AsyncSession, news_id: int) -> AsyncGenerator[str, None]:
    """SSE 生成器：meta → delta* → done / error。

    关键点：
    - 首字延迟单独打点（stream_first_token_ms），这是流式输出真正的体验指标；
    - 客户端中途断开（GeneratorExit）时不再写缓存，避免存下半截摘要。
    """
    news = await load_news(db, news_id)
    if news is None:
        yield sse_event("error", {"code": 404, "message": "新闻不存在"})
        return

    digest = content_hash(news["title"] + news["content"])
    cached = await get_cached_summary(news_id, digest)

    if cached:
        await metrics.incr("cache_hit")
        yield sse_event("meta", {"news_id": news_id, "cached": True,
                                 "model": cached.get("model", ""), "degraded": bool(cached.get("degraded"))})
        for piece in _fake_stream(cached.get("summary", "") or cached.get("text", "")):
            yield sse_event("delta", {"text": piece})
        yield sse_event("done", {"news_id": news_id, "cached": True,
                                 "elapsed_ms": 0, "tokens": {"prompt": 0, "completion": 0}})
        return

    await metrics.incr("cache_miss")
    yield sse_event("meta", {"news_id": news_id, "cached": False,
                             "model": llm_settings.model, "degraded": not llm_service.is_llm_enabled()})

    started = metrics.now_ms()
    first_token_ms: Optional[float] = None
    buffer: List[str] = []
    degraded_reason = ""

    try:
        async for piece in llm_service.stream(
            build_prompt(news["title"], news["content"]),
            system=SUMMARY_SYSTEM_PROMPT,
        ):
            if first_token_ms is None:
                first_token_ms = metrics.now_ms() - started
                await metrics.observe_latency("stream_first_token_ms", first_token_ms)
            buffer.append(piece)
            yield sse_event("delta", {"text": piece})
    except llm_service.LLMError as exc:
        degraded_reason = str(exc)
    except asyncio.CancelledError:
        raise
    except GeneratorExit:  # 客户端断开：不写缓存
        raise

    elapsed = metrics.now_ms() - started
    full_text = "".join(buffer).strip()

    if not full_text:
        # 一个 token 都没吐出来 → 降级（未配置 Key、网络失败、超时都会走到这里）
        payload = fallback_summary(
            news["title"], news["description"], news["content"],
            degraded_reason or "大模型未返回内容（未配置 Key 或调用失败）",
        )
        payload.update({"news_id": news_id, "content_hash": digest, "cached": False})
        for piece in _fake_stream(payload["summary"]):
            yield sse_event("delta", {"text": piece})
        yield sse_event("done", {
            "news_id": news_id, "cached": False, "degraded": True,
            "degrade_reason": payload["degrade_reason"], "notice": payload["notice"],
            "elapsed_ms": round(elapsed, 1), "first_token_ms": None,
            "tokens": {"prompt": 0, "completion": 0},
        })
        return

    parsed = parse_summary(full_text)
    payload = {
        **parsed,
        "news_id": news_id,
        "content_hash": digest,
        "degraded": False,
        "degrade_reason": "",
        "notice": "",
        "model": llm_settings.model,
        "source": "llm",
        "text": full_text,
        "first_token_ms": round(first_token_ms, 1) if first_token_ms else None,
    }
    await set_cached_summary(news_id, digest, payload)
    yield sse_event("done", {
        "news_id": news_id, "cached": False, "degraded": False,
        "elapsed_ms": round(elapsed, 1),
        "first_token_ms": round(first_token_ms, 1) if first_token_ms else None,
        "tokens": {"prompt": 0, "completion": 0},
        "parsed": {k: payload[k] for k in ("summary", "points", "keywords")},
    })


# ---------------------------------------------------------------------------
# 批量摘要（后台任务）
# ---------------------------------------------------------------------------
async def batch_get_summaries(
    db: AsyncSession,
    news_ids: List[int],
    concurrency: Optional[int] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """并发为多条新闻生成摘要。

    为什么要限并发：大模型服务通常有 QPS/并发限制，无脑 asyncio.gather 会被限流；
    这里用 Semaphore 控制并发度（默认 3，可配置）。
    """
    limit = max(1, concurrency or llm_settings.batch_concurrency)
    semaphore = asyncio.Semaphore(limit)
    started = metrics.now_ms()
    results: Dict[int, Dict[str, Any]] = {}
    failed: List[int] = []

    async def one(news_id: int) -> None:
        async with semaphore:
            try:
                payload, hit = await get_summary(db, news_id, use_cache=use_cache)
                if payload is None:
                    failed.append(news_id)
                else:
                    payload["cached"] = bool(hit)
                    results[news_id] = payload
            except Exception as exc:  # noqa: BLE001 - 单条失败不影响整批
                failed.append(news_id)
                results[news_id] = {"news_id": news_id, "error": str(exc)}

    await asyncio.gather(*(one(nid) for nid in news_ids))

    await metrics.incr("batch_items", len(news_ids))
    await metrics.incr("batch_failed_items", len(failed))
    elapsed = metrics.now_ms() - started

    return {
        "items": [results[nid] for nid in news_ids if nid in results],
        "failed_ids": failed,
        "total": len(news_ids),
        "success": len(news_ids) - len(failed),
        "elapsed_ms": round(elapsed, 1),
        "concurrency": limit,
    }
