from pydantic import BaseModel, Field,ConfigDict
from datetime import datetime

class FavoriteCheckResponse(BaseModel):
    is_favorite: bool = Field(...,alias="isFavorite")


class FavoriteAddRequest(BaseModel):
    news_id: int = Field(...,alias="newsId")



# 规划两个类:一个是新闻模型类+收藏的模型类

from schemas.base import NewsItemBase
class FavoriteNewsItemResponse(NewsItemBase):
    favorite_id: int = Field(alias="favoriteId")
    favorite_time: datetime = Field(alias="favoriteTime")
    
    model_config = ConfigDict(
            from_attributes=True,
            populate_by_name=True
        )




class FavoriteListResponse(BaseModel):
    list: list[FavoriteNewsItemResponse]
    total: int 
    has_more: bool = Field(alias="hasMore")

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True
    )
