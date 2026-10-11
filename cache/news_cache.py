# 新闻相关的缓存方法：新闻分类的读取和写入
# key-value
from config.cache_conf import get_json_cache, set_cache
from typing import List, Dict, Any, Optional

# 新闻分类缓存key
CATEGORIES_KEY = 'news:categories'
NEWS_LIST_PREFIX = 'news:list'



# 获取新闻分类缓存
async def get_cache_categories():
    return await get_json_cache(CATEGORIES_KEY)



# 写入新闻分类缓存:缓存的数据，过期时间
# 分类、配置 7200；列表：600；详情：1800；验证码：120---数据越稳定，缓存越久
async def set_cache_categories(data: List[Dict[str, Any]], expire: int = 7200):
    return await set_cache(CATEGORIES_KEY, data, expire)




# 写入缓存方法-新闻列表   key = news_list:category_id:page:pagesize  +  列表数据  +  过期时间
async def set_cache_news_list(category_id:Optional[int], page:int ,pagesize : int, news_list: List[Dict[str, Any]], expire: int = 1800):
    category_part = category_id if category_id is not None else 'all'
    key = f"{NEWS_LIST_PREFIX}:{category_part}:{page}:{pagesize}"
    return await set_cache(key, news_list, expire)



# 读取缓存方法-新闻列表
async def get_cache_news_list(category_id:Optional[int], page:int ,pagesize : int):
    category_part = category_id if category_id is not None else 'all'
    key = f"{NEWS_LIST_PREFIX}:{category_part}:{page}:{pagesize}"
    return await get_json_cache(key)


# 读取缓存方法-新闻数量
async def get_cache_news_count(news_id:Optional[int]):
    key = f"{NEWS_LIST_PREFIX}:{news_id}:count"
    return await get_json_cache(key)

# 写入缓存方法-新闻数量
async def set_cache_news_count(news_id:Optional[int], count: int, expire: int = 3600):
    key = f"{NEWS_LIST_PREFIX}:{news_id}:count"
    return await set_cache(key, count, expire)

# 读取缓存方法-新闻详情
async def get_cache_news_detail(news_id:Optional[int]):
    key = f"{NEWS_LIST_PREFIX}:{news_id}:detail"
    return await get_json_cache(key)

# 写入缓存方法-新闻详情
async def set_cache_news_detail(news_id:Optional[int], news_detail: Dict[str, Any], expire: int = 3600):
    key = f"{NEWS_LIST_PREFIX}:{news_id}:detail"
    return await set_cache(key, news_detail, expire)






