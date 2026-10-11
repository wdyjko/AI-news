from fastapi import APIRouter,Body,Depends,status

from utils.response import sucess_response
router = APIRouter(prefix="/api/user",tags=["users"])

from schemas.users import UserRequest,UserInfoResponse,UserAuthResponse
from config.db_conf import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from crud import users
from fastapi import HTTPException
from utils.auth import get_current_user
from models.users import User
from schemas.users import UserChangePasswordRequest
from schemas.users import UserUpdateRequest

@router.post("/register")
async def register(db: AsyncSession = Depends(get_db),user_data:UserRequest = Body(...)): #用户信息和数据库会话
    # 注册逻辑：验证用户是否存在--创建用户--生成token--响应结果
    existing_user = await users.get_user_by_username(db,user_data.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = await users.create_user(db,user_data)


    # 生成token
    token = await users.create_token(db,user.id)

    response_data=UserAuthResponse(token=token,user_info=UserInfoResponse.model_validate(user))
    return sucess_response(message='注册成功',data=response_data)

    #     return {
    #     "code": 200,
    #     "message": "注册成功",
    #     "data": {
    #         "token": token,
    #         "userInfo": {
    #         "id": user.id,
    #         "username": user.username,
    #         "bio": user.bio,
    #         "avatar": user.avatar,
    #         }
    #     }
    # }


@router.post("/login")
async def login(db: AsyncSession = Depends(get_db),user_data:UserRequest = Body(...)):
    # 登录逻辑：验证用户是否存在--验证密码--生成token--响应结果
    user = await users.authenticate_user(db,user_data.username,user_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = await users.create_token(db,user.id)
    response_data=UserAuthResponse(token=token,user_info=UserInfoResponse.model_validate(user))
    return sucess_response(message='登录成功',data=response_data)


# 查Token查用户--封装curd--功能整合成一个工具函数--路由导入使用
@router.get("/info")
async def get_user_info(user: User = Depends(get_current_user)):

    response_data=UserInfoResponse.model_validate(user)
    return sucess_response(message='获取用户信息成功',data=response_data)


@router.put("/update")
async def update_user_info(
    user: User = Depends(get_current_user),
    update_data: UserUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db)
    ):
    # 修改个人资料（前端「个人简介」保存用这个接口）
    updated_user = await users.update_user_info(db, user, update_data)
    response_data = UserInfoResponse.model_validate(updated_user)
    return sucess_response(message='修改成功', data=response_data)


@router.put("/password")
async def update_password(
    user:User = Depends(get_current_user),
    password_data:UserChangePasswordRequest = Body(...),
    db: AsyncSession = Depends(get_db)
    ):
    
    res_change_pwd = await users.change_password(db,user,password_data)
    if not res_change_pwd:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="密码修改失败")

    return sucess_response(message='密码修改成功')

