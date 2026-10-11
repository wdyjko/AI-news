from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select,delete,func
from models.favorite import Favorite
from models.news import News




async def is_news_favorite(
    db: AsyncSession, 
    user_id: int, 
    news_id: int
    ):
    """
    检查当前用户是否收藏了新闻
    """

    query = select(Favorite).where(Favorite.user_id == user_id, Favorite.news_id == news_id)
    result = await db.execute(query)
    
    # 检查查询结果是否为空(是否有收藏记录)
    return result.scalar_one_or_none() is not None


async def add_news_favorite(
    db: AsyncSession, 
    user_id: int, 
    news_id: int
    ):
    """
    添加新闻收藏记录
    """
    favorite_record = Favorite(user_id=user_id, news_id=news_id)
    db.add(favorite_record)
    await db.commit()
    await db.refresh(favorite_record)
    return favorite_record


async def remove_news_favorite(
    db: AsyncSession, 
    user_id: int, 
    news_id: int
    ):
    """
    删除新闻收藏记录
    """
    stmt = delete(Favorite).where(Favorite.user_id == user_id, Favorite.news_id == news_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


# 获取用户收藏列表:获取的是某个用户的收藏列表+分页功能
async def get_favorite_list(
    db: AsyncSession, 
    user_id: int, 
    page: int = 1, 
    page_size: int = 10
    ):
    """
    获取用户收藏列表
    """
    count_query = select(func.count(Favorite.id)).where(Favorite.user_id == user_id)
    count_result = await db.execute(count_query)
    total_count = count_result.scalar_one_or_none()

    # 获取收藏列表--连表查询join()+收藏时间排序+分页查询
    offset = (page - 1) * page_size
    #[(News,Favorite.created_at,favorite_id)]
    query = (
        select(News, Favorite.created_at.label("favorite_time"), Favorite.id.label("favorite_id"))
        .join(Favorite, News.id == Favorite.news_id)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()
    return rows,total_count


async def clear_favorite(
    db: AsyncSession, 
    user_id: int
    ):
    """
    清空用户收藏记录
    """
    stmt = delete(Favorite).where(Favorite.user_id == user_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0



