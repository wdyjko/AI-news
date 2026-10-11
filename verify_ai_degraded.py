# -*- coding: utf-8 -*-
"""降级路径验证：大模型不可用时，接口必须仍然可用（返回 200 + degraded 标记，绝不 5xx）。

模拟两种故障：
    A. 未配置 Key           → 直接走原文摘录
    B. Key 无效 / 上游 401   → 真实发一次请求，拿到错误后降级

跑法：
    venv\\Scripts\\python.exe verify_ai_degraded.py
"""

from __future__ import annotations

import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.abspath(__file__))
REPORT: list[str] = []

CHILD_CODE = r'''
import asyncio, json, os, sys, time
sys.path.insert(0, PROJECT_DIR)
from config.db_conf import async_engine
async_engine.echo = False
import httpx
from httpx import ASGITransport
from sqlalchemy import text
from config.db_conf import AsyncSessionLocal
from main import app

async def main():
    async with AsyncSessionLocal() as db:
        news_id = (await db.execute(text(
            "SELECT id FROM news ORDER BY CHAR_LENGTH(content) DESC LIMIT 1"))).scalar_one()
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=60) as c:
        health = (await c.get("/api/ai/health")).json()["data"]
        print("HEALTH", json.dumps(health, ensure_ascii=False))

        t0 = time.perf_counter()
        first = (await c.get(f"/api/ai/news/summary?id={news_id}")).json()
        ms1 = (time.perf_counter() - t0) * 1000
        d1 = first.get("data") or {}
        print("HTTP message =", first.get("message"))
        print("cached =", d1.get("cached"), " degraded =", d1.get("degraded"))
        print("summary =", d1.get("summary"))
        print("degrade_reason =", d1.get("degrade_reason"))
        print("notice =", d1.get("notice"))
        print("first_call_ms = %.1f" % ms1)

        t1 = time.perf_counter()
        second = (await c.get(f"/api/ai/news/summary?id={news_id}")).json()
        ms2 = (time.perf_counter() - t1) * 1000
        d2 = second.get("data") or {}
        print("second call: cached =", d2.get("cached"), " client_ms = %.1f" % ms2)
        print("=> 降级结果已缓存" if d2.get("cached") else "=> 降级结果未缓存")

asyncio.run(main())
'''


def log(line: str = "") -> None:
    print(line)
    REPORT.append(line)


def scenario(title: str, env_override: dict) -> None:
    log("=" * 88)
    log(f"### {title}")
    log("=" * 88)
    child = CHILD_CODE.replace("PROJECT_DIR", repr(PROJECT))
    # 独立缓存命名空间：否则会命中上一次"真实大模型"跑出来的缓存，测不到降级路径
    env = {
        **os.environ,
        "SUMMARY_CACHE_VERSION": "degraded-test-%d" % int(__import__("time").time()),
        **env_override,
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.run(
        [sys.executable, "-c", child],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    for line in (proc.stdout or "").splitlines():
        log("  " + line)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        log("  [stderr] " + (tail[-1][:200] if tail else "unknown error"))
    log("")


def main() -> None:
    scenario("A. 未配置 LLM_API_KEY（纯降级）", {"LLM_API_KEY": ""})
    scenario("B. Key 无效（上游返回 401，验证失败降级）",
             {"LLM_API_KEY": "sk-invalid-key-for-degrade-test"})

    out = os.path.join(PROJECT, "verify_ai_degraded_result.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(REPORT))
    print(f"报告已保存：{out}")


if __name__ == "__main__":
    main()
