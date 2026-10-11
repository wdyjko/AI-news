import redis.asyncio as redis
import json
from typing import Any

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0



# 创建Redis的连接对象
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,  # Redis数据库编号,0~15
    decode_responses=True,  # 是否将Redis返回的字符串解码为Python字符串
    protocol=2  # 使用RESP2协议，兼容Redis 5.x(不支持HELLO命令)
)

# 设置 和 读取 (字符串 和 列表或字典) "[{}]"
# 读取：字符串
async def get_cache(key: str):
    # return await redis_client.get(key)
    try:
        return await redis_client.get(key)
    except Exception as e:
        print(f"读取缓存失败：{e}")
        return None





# 读取：列表或字典
async def get_json_cache(key: str):
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        print(f"读取JSON缓存失败：{e}")
        return None





# 设置缓存
async def set_cache(key: str, value: Any, expire: int = 3600):
    try:
        if isinstance(value, (dict , list)):
            value = json.dumps(value,ensure_ascii=False)# 中文正常保存
        await redis_client.setex(key, expire, value)
        return True
    except Exception as e:
        print(f"设置缓存失败：{e}")
        return False







