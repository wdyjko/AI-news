"""大模型客户端（OpenAI 兼容 /chat/completions）。

只做三件事，但都要做对：
1. **异步流式**：SSE 逐块 yield 文本，前端能边生成边显示（首字延迟是体验的核心指标）；
2. **超时可控**：连接超时与读取超时分开，避免上游卡住把整个请求挂死；
3. **失败可判**：把"没配 Key"和"调用失败"区分开 —— 前者是配置问题，后者是网络/额度问题，
   两者给用户的提示完全不同（这一点直接影响线上排障效率）。

依赖：httpx（FastAPI 生态标准依赖，已加入 requirements.txt）。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from config.llm_conf import llm_settings
from services import metrics


class LLMError(Exception):
    """大模型调用失败（网络/超时/额度/返回体异常）。"""


@dataclass
class LLMResult:
    """一次非流式调用的结果。"""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 1
    model: str = ""
    degraded: bool = False
    degrade_reason: str = ""
    meta: Dict[str, str] = field(default_factory=dict)


def is_llm_enabled() -> bool:
    """是否配置了可用的大模型 Key。"""
    return llm_settings.enabled


def _prepare_messages(prompt: str, system: Optional[str]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _build_payload(messages: List[Dict[str, str]], stream: bool) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "model": llm_settings.model,
        "messages": messages,
        "temperature": llm_settings.temperature,
        "stream": stream,
    }
    # 部分服务商对 max_tokens 字段名不同，这里只在显式配置时下发，兼容性更好
    if llm_settings.max_tokens:
        payload["max_tokens"] = llm_settings.max_tokens
    if stream:
        # 让 OpenAI 兼容服务在最后一个 chunk 里带上 usage
        payload["stream_options"] = {"include_usage": True}
    return payload


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {llm_settings.api_key}",
        "Content-Type": "application/json",
    }


def _make_client() -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        llm_settings.timeout,
        connect=llm_settings.connect_timeout,
    )
    return httpx.AsyncClient(base_url=llm_settings.base_url, timeout=timeout)


def _extract_error(response: httpx.Response) -> str:
    detail = ""
    try:
        body = response.json()
        detail = str(body.get("error", {}).get("message") or body)[:200]
    except Exception:  # noqa: BLE001 - 返回体不是 JSON 时只取文本片段
        detail = (response.text or "")[:200]
    return f"HTTP {response.status_code}: {detail}"


async def _post_with_retry(client: httpx.AsyncClient, payload: Dict[str, object]) -> httpx.Response:
    """POST 并做有限重试：只对 5xx / 网络错误重试，4xx 直接失败（重试没意义还烧钱）。"""
    last_error: Optional[Exception] = None
    attempts = max(0, llm_settings.max_retry) + 1
    for attempt in range(1, attempts + 1):
        try:
            response = await client.post("/chat/completions", json=payload, headers=_headers())
            if response.status_code >= 500 and attempt < attempts:
                await metrics.incr("llm_retry")
                await asyncio.sleep(0.5 * attempt)
                continue
            return response
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt < attempts:
                await metrics.incr("llm_retry")
                await asyncio.sleep(0.5 * attempt)
                continue
            break
    raise LLMError(f"大模型请求失败：{last_error}")


async def complete(prompt: str, system: Optional[str] = None) -> LLMResult:
    """非流式调用，返回完整文本与 token 用量。"""
    if not is_llm_enabled():
        return LLMResult(text="", degraded=True, degrade_reason="未配置 LLM_API_KEY（纯检索降级模式）")

    await metrics.incr("llm_calls")
    payload = _build_payload(_prepare_messages(prompt, system), stream=False)

    try:
        async with _make_client() as client:
            response = await _post_with_retry(client, payload)
            if response.status_code >= 400:
                raise LLMError(_extract_error(response))
            body = response.json()
    except LLMError as exc:
        await metrics.incr("llm_failed")
        await metrics.incr("llm_degraded")
        return LLMResult(text="", degraded=True, degrade_reason=str(exc))
    except Exception as exc:  # noqa: BLE001 - 任何意外都要变成可读的降级结果
        await metrics.incr("llm_failed")
        await metrics.incr("llm_degraded")
        return LLMResult(text="", degraded=True, degrade_reason=f"调用异常：{exc}")

    try:
        text = (body["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        await metrics.incr("llm_failed")
        await metrics.incr("llm_degraded")
        return LLMResult(text="", degraded=True, degrade_reason=f"返回体结构异常：{exc}")

    usage = body.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    await metrics.incr("llm_success")
    await metrics.add_tokens(prompt_tokens, completion_tokens)

    return LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=str(body.get("model") or llm_settings.model),
    )


async def stream(prompt: str, system: Optional[str] = None) -> AsyncGenerator[str, None]:
    """流式调用，逐块 yield 文本增量。

    注意：调用方必须处理"一个块都没吐出来"的情况（网络断开），
    所以这里把异常转成结束（yield 完就 return），由上层决定是否降级。
    """
    if not is_llm_enabled():
        return

    await metrics.incr("llm_calls")
    await metrics.incr("stream_requests")
    payload = _build_payload(_prepare_messages(prompt, system), stream=True)
    prompt_tokens = completion_tokens = 0

    try:
        async with _make_client() as client:
            async with client.stream("POST", "/chat/completions", json=payload, headers=_headers()) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise LLMError(f"HTTP {response.status_code}: {body[:200]!r}")

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    usage = chunk.get("usage") or {}
                    if usage:
                        prompt_tokens = int(usage.get("prompt_tokens") or prompt_tokens or 0)
                        completion_tokens = int(usage.get("completion_tokens") or completion_tokens or 0)

                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            yield piece

        await metrics.incr("llm_success")
        await metrics.add_tokens(prompt_tokens, completion_tokens)
    except Exception as exc:  # noqa: BLE001
        await metrics.incr("llm_failed")
        await metrics.incr("llm_degraded")
        raise LLMError(f"流式调用失败：{exc}") from exc
