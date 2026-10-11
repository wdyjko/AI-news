"""AI 摘要相关的请求/响应模型。"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class BatchSummaryRequest(BaseModel):
    newsIds: List[int] = Field(..., min_length=1, description="要生成摘要的新闻 id 列表")
    concurrency: Optional[int] = Field(None, ge=1, le=10, description="并发度，默认取服务端配置")
    useCache: bool = Field(True, description="是否允许使用摘要缓存")
    forceRefresh: bool = Field(False, description="为 True 时忽略已有缓存，强制重新生成")

    @field_validator("newsIds")
    @classmethod
    def _dedup(cls, value: List[int]) -> List[int]:
        # 去重且保持顺序：同一批里重复请求同一条新闻没有意义，还会浪费 token
        seen: Dict[int, None] = {}
        for item in value:
            seen.setdefault(int(item), None)
        return list(seen.keys())


class SummaryTokens(BaseModel):
    prompt: int = 0
    completion: int = 0


class SummaryData(BaseModel):
    news_id: Optional[int] = None
    summary: str = ""
    points: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    degraded: bool = False
    degrade_reason: str = ""
    notice: str = ""
    model: str = ""
    source: str = ""
    cached: bool = False
    elapsed_ms: float = 0.0
    first_token_ms: Optional[float] = None
    tokens: Optional[SummaryTokens] = None


class BatchTaskCreated(BaseModel):
    task_id: str
    status: str
    total: int


class BatchTaskStatus(BaseModel):
    task_id: str
    status: str
    total: int
    finished: int
    failed_ids: List[int] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    data: Optional[Dict] = None
