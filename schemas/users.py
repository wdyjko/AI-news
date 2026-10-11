from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

class UserRequest(BaseModel):
    username: str
    password: str

# user_info对应的类
class UserInfoBase(BaseModel): #对应的类:基础类+Info类(id,用户名)
    nickname:Optional[str] = Field(None,max_length=50,description="用户昵称")
    avatar:Optional[str] = Field(None,max_length=255,description="用户头像")
    gender:Optional[int] = Field(None,max_length=10,description="用户性别")
    bio:Optional[str] = Field(None,max_length=500,description="用户简介")


class UserInfoResponse(UserInfoBase): 
    id: int
    username: str

    # 模型类配置
    model_config = ConfigDict(
        from_attributes=True # 允许从orm对象中获取数据
        )



# data数据类型对应的类
class UserAuthResponse(BaseModel):
    token: str
    user_info: UserInfoResponse = Field(...,alias="userInfo")

    # 模型类配置
    model_config = ConfigDict(
        populate_by_name=True, #alias/字段名兼容
        from_attributes=True # 允许从orm对象中获取数据
        )



class UserChangePasswordRequest(BaseModel):
    old_password: str = Field(...,alias="oldPassword",qdescription="旧密码")
    new_password: str = Field(...,min_length=6,alias="newPassword",description="新密码")


class UserUpdateRequest(UserInfoBase):
    """修改个人资料（昵称/头像/性别/简介）。

    全部字段可选：只更新请求里出现的字段（配合 exclude_unset），
    避免前端只想改简介却把昵称、头像一起清空。
    """







