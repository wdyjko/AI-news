"""AI 摘要缓存：按「新闻正文内容 hash」缓存，正文不变则永久复用。

为什么不是只按 news_id 缓存？
    news_id 只能标识"哪条新闻"，标识不了"哪一版内容"。新闻被编辑（或同一 id 换了正文）后，
    按 id 缓存会返回过期的旧摘要。用 content_hash 做 key 的组成部分，正文一变 key 自然失效，
    不需要任何主动清理逻辑。

key 结构：
    news:summary:{version}:{news_id}:{content_hash[:16]}

复用 config.cache_conf 里已有的 redis 客户端与读写封装（连接异常时自动降级为"无缓存"）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from config.cache_conf import get_json_cache, redis_client, set_cache
from config.llm_conf import llm_settings

SUMMARY_KEY_PREFIX = "news:summary"
# 记录"某条新闻最近一次生成的摘要 key"，便于正文变更后清理旧 key
SUMMARY_INDEX_PREFIX = "news:summary:index"


def content_hash(text: str) -> str:
    """正文指纹：空白归一化后再 hash，避免仅换行/空格差异导致缓存失效。"""
    normalized = " ".join((text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_summary_key(news_id: Optional[int], digest: str) -> str:
    return f"{SUMMARY_KEY_PREFIX}:{llm_settings.cache_version}:{news_id}:{digest[:16]}"


def build_index_key(news_id: Optional[int]) -> str:
    return f"{SUMMARY_INDEX_PREFIX}:{news_id}"


async def get_cached_summary(news_id: Optional[int], digest: str) -> Optional[Dict[str, Any]]:
    """读摘要缓存；未命中或 Redis 异常都返回 None（由调用方回源）。"""
    if not digest:
        return None
    return await get_json_cache(build_summary_key(news_id, digest))


async def set_cached_summary(
    news_id: Optional[int],
    digest: str,
    payload: Dict[str, Any],
    expire: Optional[int] = None,
) -> bool:
    """写摘要缓存，并记录索引 key（正文变更后可据此失效旧摘要）。

    expire 允许按结果类型区分有效期：正常摘要可以放很久（正文不变就永远有效），
    降级摘要要短一些（大模型恢复后能尽快拿到真正的摘要）。
    """
    if not digest:
        return False
    ttl = int(expire or llm_settings.cache_expire)
    new_key = build_summary_key(news_id, digest)
    index_key = build_index_key(news_id)

    ok = await set_cache(new_key, payload, ttl)

    # 维护"历史 key"索引：正文更新后，旧摘要不再被命中，这里顺手删掉避免占用内存
    try:
        old_key = await redis_client.get(index_key)
        if old_key and old_key != new_key:
            await redis_client.delete(old_key)
        await redis_client.setex(index_key, ttl, new_key)
    except Exception:
        # 索引只是优化项，失败不影响主流程
        pass
    return ok
