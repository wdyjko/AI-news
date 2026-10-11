from fastapi import APIRouter, Query
from models.users import User
from fastapi import Depends
from utils.auth import get_current_user
from config.db_conf import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from utils.response import sucess_response
from crud import favorite
from schemas.favorite import FavoriteCheckResponse,FavoriteAddRequest
from fastapi import Body,HTTPException,status
from schemas.favorite import FavoriteListResponse



router = APIRouter(prefix="/api/favorite",tags=["favorite"])

@router.get("/check")
async def check_favorite(
    news_id: int = Query(...,alias="newsId"),
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user)
    ):

    # 检查用户是否收藏了该文章
    is_favorited = await favorite.is_news_favorite(db,user.id,news_id)
    
    return sucess_response(message='检查收藏成功',data=FavoriteCheckResponse(isFavorite=is_favorited))


@router.post("/add")
async def add_favorite(
    data:FavoriteAddRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user)
    ):

    # 添加收藏记录
    result = await favorite.add_news_favorite(db,user.id,data.news_id)
    return sucess_response(message='收藏成功',data=result)


@router.delete("/remove")
async def remove_favorite(
    news_id: int = Query(...,alias="newsId"),
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user)
    ):

    # 删除收藏记录
    result = await favorite.remove_news_favorite(db, user.id, news_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未收藏该新闻")
    return sucess_response(message='取消收藏成功')


@router.get("/list")
async def get_favorite_list(
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user),
    page: int = Query(1,ge=1),
    page_size: int = Query(10,alias="pageSize",ge=1,le=100)
    ):

    # 获取用户收藏列表
    rows,total_count = await favorite.get_favorite_list(db,user.id,page,page_size)
    favorite_list = [{
        **news.__dict__,
        "favoriteTime": favorite_time,
        "favoriteId": favorite_id,
    } for news,favorite_time,favorite_id in rows]
    
    has_more = total_count > page * page_size
    data = FavoriteListResponse(list=favorite_list,total=total_count,hasMore=has_more)

    return sucess_response(message='获取收藏列表成功',data=data)


@router.delete("/clear")
async def clear_favorite(
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user)
    ):

    # 清空用户收藏记录
    count = await favorite.clear_favorite(db,user.id)
    return sucess_response(message=f'清空收藏成功，共删除{count}条记录')






