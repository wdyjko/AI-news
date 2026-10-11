from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from models.users import User, UserToken
from schemas.users import UserRequest
from utils import security
from datetime import datetime, timedelta
from schemas.users import UserChangePasswordRequest

# 根据用户名查询数据

async def get_user_by_username(db: AsyncSession, username: str):

    return (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()


# 创建用户
async def create_user(db: AsyncSession, user_data: UserRequest):
    # 先密码加密处理--add
    hashed_password = security.get_hash_password(user_data.password)
    user = User(**user_data.model_dump(exclude={"password"}), password=hashed_password)
    db.add(user)
    await db.commit()
    await db.refresh(user) # 从数据库读回最新的用户数据
    return user

# 生成Token
async def create_token(db: AsyncSession, user_id: int):
    # 生成Token+设置过期时间--查询数据库当前用户是否有token--有，更新，无，创建
    token = str(uuid.uuid4())
    # timedelta(days=7,hours=2,minutes=30,seconds=20) 表示7天2小时30分钟20秒后过期
    expired_at = datetime.now() + timedelta(days=7)
    query = select(UserToken).where(UserToken.user_id == user_id)
    result = await db.execute(query)
    user_token = result.scalar_one_or_none()
    # 如果用户有token，更新token和过期时间
    if user_token:
        user_token.token = token
        user_token.expires_at = expired_at
    else:
        # 如果用户没有token，创建新token
        user_token = UserToken(token=token, user_id=user_id, expires_at=expired_at)
        db.add(user_token)
    await db.commit()
    await db.refresh(user_token)
    return token


async def authenticate_user(db:AsyncSession,username:str,password:str):
    user = await get_user_by_username(db,username)
    if not user:
        return None
    if not security.verify_password(password,user.password):
        return None

    return user


# 根据token查询用户：验证Token--查询用户
async def get_user_by_token(db: AsyncSession, token: str):
    query = select(UserToken).where(UserToken.token == token)
    result = await db.execute(query)
    db_token = result.scalar_one_or_none()
    if not db_token or db_token.expires_at < datetime.now():
        return None
    
    query = select(User).where(User.id == db_token.user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()
 

# 修改个人资料：只更新请求里显式传了的字段
async def update_user_info(db: AsyncSession, user: User, update_data):
    # exclude_unset=True：没传的字段不参与更新，避免被覆盖成 None
    fields = update_data.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        return user
    for key, value in fields.items():
        setattr(user, key, value)
    # 更新：由sqlalchemy真正接管user对象，确保可以commit
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# 修改密码：验证旧密码--新密码加密--修改密码
async def change_password(db: AsyncSession, user: User, password_data: UserChangePasswordRequest):
    # 验证旧密码
    if not security.verify_password(password_data.old_password, user.password):
        return False
    # 新密码加密
    new_password = security.get_hash_password(password_data.new_password)
    user.password = new_password
    # 更新：由sqlalchemy真正接管user对象，确保可以commit
    # 规避session过期或关闭导致的不能提交的问题
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return True










