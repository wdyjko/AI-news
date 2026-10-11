from pydantic import BaseModel, Field
from models.history import History
from schemas.base import NewsItemBase
from datetime import datetime
from pydantic import ConfigDict



class HistoryAddRequest(BaseModel):
    news_id: int = Field(...,alias="newsId")




class HistoryNewsItemResponse(NewsItemBase):
    view_time: datetime = Field(alias="viewTime")
    
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True
    )



class HistoryListResponse(BaseModel):
    list: list[HistoryNewsItemResponse]
    total: int
    has_more: bool = Field(alias="hasMore")

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True
    )












