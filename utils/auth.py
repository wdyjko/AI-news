from fastapi import Header,HTTPException,status,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from config.db_conf import get_db
from crud.users import get_user_by_token



# 整合 根据Token查询用户，返回用户
async def get_current_user(db: AsyncSession = Depends(get_db), authorization: str = Header(...,alias="Authorization")):
    #Bearer token
    #token = authorization.split(" ")[1]
    token = authorization.replace("Bearer ","")
    
    user = await get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的令牌或者令牌过期")
    return user



















