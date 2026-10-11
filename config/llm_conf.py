"""大模型（AI 摘要）相关配置。

设计原则：
1. 不引入新依赖 —— 只用标准库读 .env，不依赖 python-dotenv / pydantic-settings；
2. 任何 Key 缺失都不影响服务启动 —— 此时 is_llm_enabled() 为 False，接口自动走降级逻辑；
3. 所有可调参数集中在这里，方便按"缓存 / 成本 / 超时"三个维度调优。

.env 示例（放在项目根目录，不要提交到 Git）：
    LLM_API_KEY=sk-xxx
    LLM_BASE_URL=https://api.deepseek.com/v1
    LLM_MODEL=deepseek-chat
    LLM_TIMEOUT=30
    LLM_MAX_RETRY=1
    LLM_MAX_INPUT_CHARS=4000
    SUMMARY_CACHE_EXPIRE=604800
    SUMMARY_CACHE_VERSION=v1
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# 项目根目录（本文件位于 config/ 下）
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def _load_env_file(path: Path) -> None:
    """极简 .env 解析：KEY=VALUE，支持 # 注释与首尾引号。

    已存在的真实环境变量优先，不会被 .env 覆盖（方便容器/CI 注入）。
    """
    if not path.exists():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        # 读不到 .env 不应该影响启动
        pass


_load_env_file(ENV_FILE)


def _get_str(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _get_int(key: str, default: int) -> int:
    try:
        return int(_get_str(key) or default)
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(_get_str(key) or default)
    except ValueError:
        return default


class LLMSettings:
    """AI 摘要相关的全部配置项。"""

    # ---------- 大模型接入 ----------
    api_key: str = _get_str("LLM_API_KEY")
    base_url: str = _get_str("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model: str = _get_str("LLM_MODEL", "deepseek-chat")

    # 超时（秒）：连接 / 读取分开设，避免大模型"卡住"时把请求挂死
    connect_timeout: float = _get_float("LLM_CONNECT_TIMEOUT", 5.0)
    timeout: float = _get_float("LLM_TIMEOUT", 30.0)
    max_retry: int = _get_int("LLM_MAX_RETRY", 1)

    # 生成参数
    temperature: float = _get_float("LLM_TEMPERATURE", 0.3)
    max_tokens: int = _get_int("LLM_MAX_TOKENS", 400)

    # 送入模型的正文截断长度（控制单次调用成本；超长新闻只取前 N 字）
    max_input_chars: int = _get_int("LLM_MAX_INPUT_CHARS", 4000)

    # ---------- 缓存策略 ----------
    # 摘要缓存 key 的版本号：提示词或模型变更时改它，可让旧缓存整体失效
    cache_version: str = _get_str("SUMMARY_CACHE_VERSION", "v1")
    # 摘要缓存过期时间（秒）：默认 7 天 —— 摘要由正文决定，正文不变则永不失效
    cache_expire: int = _get_int("SUMMARY_CACHE_EXPIRE", 7 * 24 * 3600)
    # 降级摘要的缓存时间（秒）：短一些，等大模型恢复后能尽快拿到真正的摘要
    degraded_cache_expire: int = _get_int("SUMMARY_DEGRADED_CACHE_EXPIRE", 600)

    # ---------- 批量任务 ----------
    batch_concurrency: int = _get_int("SUMMARY_BATCH_CONCURRENCY", 3)
    batch_max_items: int = _get_int("SUMMARY_BATCH_MAX_ITEMS", 30)
    # 批量任务结果在 Redis 里保留多久（秒）
    task_expire: int = _get_int("SUMMARY_TASK_EXPIRE", 3600)

    @property
    def enabled(self) -> bool:
        """是否配置了可用的 Key（占位值视为未配置）。"""
        key = self.api_key
        if not key:
            return False
        lowered = key.lower()
        return not (lowered.startswith("sk-xxx") or lowered in {"none", "null", "your-key"})


llm_settings = LLMSettings()
