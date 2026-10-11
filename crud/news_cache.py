from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession
from models.news import Category
from sqlalchemy import select, func, update
from models.news import News
from cache.news_cache import get_cache_categories, set_cache_categories, get_cache_news_list, set_cache_news_list, get_cache_news_count, set_cache_news_count, get_cache_news_detail, set_cache_news_detail
from schemas.base import NewsItemBase



async def get_categories(db: AsyncSession, skip: int = 0, limit: int = 100):

    # 从缓存中获取新闻分类
    cached_categories = await get_cache_categories()
    if cached_categories:
        return cached_categories


    stmt = select(Category).offset(skip).limit(limit)
    result = await db.execute(stmt)
    categories = result.scalars().all() #orm对象
    
    # 写入缓存新闻分类
    if categories:
        categories = jsonable_encoder(categories)#jsonable_encoder 可以将orm对象转换为字典，再写入缓存
        await set_cache_categories(categories)
    return categories



async def get_news_list(db:AsyncSession, category_id:int, skip:int=0, limit:int=10):

    # 从缓存中获取新闻列表
    page = skip // limit + 1
    cached_list = await get_cache_news_list(category_id, page, limit)
    if cached_list:
        # return cached_list # 要的是orm对象
        return [News(**item) for item in cached_list]



    # 查询指定分类下的所有新闻，每次展示limit条，从skip条开始展示
    # scalars() 表示返回一个迭代器，每次迭代返回一个orm对象
    stmt = select(News).where(News.category_id == category_id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    news_list = result.scalars().all()

    # 写入缓存新闻列表
    if news_list:
        # 先把orm数据转换成字典才能写入缓存
        # orm转成pydantic，再转为字典
        # by_alias=False 表示不使用别名，而是使用原始字段名,保存Python风格，因为redis数据是给后端用的
        # mode='json' 表示将字典转换为JSON字符串，而不是Python对象的字符串表示
        # model_validate(news) 表示将orm对象转换为pydantic模型
        # model_dump表示将pydantic模型转换为字典
        news_data = [NewsItemBase.model_validate(news).model_dump(mode = 'json',by_alias=False) for news in news_list]
        await set_cache_news_list(category_id, page, limit, news_data)
    return news_list



async def get_news_count(db:AsyncSession, category_id:int):


    # 从缓存中获取新闻数量
    cached_count = await get_cache_news_count(category_id)
    if cached_count:
        return cached_count

    # 查询指定分类下的新闻数量
    stmt = select(func.count(News.id)).where(News.category_id == category_id)
    result = await db.execute(stmt)
    news_count = result.scalar_one() # 返回一个整数，即指定分类下的新闻数量
    
    # 写入缓存新闻数量
    await set_cache_news_count(category_id, news_count)
    return news_count



async def get_news_detail(db:AsyncSession, news_id:int):

    # 从缓存中获取新闻详情
    cached_detail = await get_cache_news_detail(news_id)
    if cached_detail:
        # 修复：缓存里存的是 dict，而本函数的另一条分支返回 ORM 对象（News）。
        # 同一函数返回两种类型会让调用方（详情路由）在缓存命中时访问 .id / .content 直接报错。
        # 这里与 get_news_list 的写法保持一致，把 dict 还原成 News 对象，保证返回类型统一。
        return News(**cached_detail)


    # 查询指定新闻的详细信息
    stmt = select(News).where(News.id == news_id)
    result = await db.execute(stmt)
    news = result.scalar_one_or_none()
    if news is None:
        return None


    # 写入缓存新闻详情
    news_detail = NewsItemBase.model_validate(news).model_dump(mode = 'json',by_alias=False)
    await set_cache_news_detail(news_id, news_detail)
    return news



async def update_news_views(db:AsyncSession, news_id:int):
    result = await db.execute(update(News).where(News.id == news_id).values(views=News.views + 1))
    await db.commit()

    # 检查数据库是否命中数据，如果有则返回True，否则返回False
    return result.rowcount > 0
    

async def get_related_news(db:AsyncSession, news_id:int,category_id:int,limit:int=5):
    # 查询与指定新闻相关的其他新闻
    stmt = select(News).where(News.id != news_id, News.category_id == category_id).order_by(News.views.desc(),News.publish_time.desc()).limit(limit)
    result = await db.execute(stmt)
    # return result.scalars().all()
    related_news = result.scalars().all()
    # 列表推导式
    return [{'id':news_detail.id,
            'title':news_detail.title,
            'content':news_detail.content,
            'image':news_detail.image,
            'author':news_detail.author,
            'publish_time':news_detail.publish_time,
            'category_id':news_detail.category_id,
            'views':news_detail.views,} for news_detail in related_news]
