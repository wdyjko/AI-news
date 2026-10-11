from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String, Index, Enum, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from datetime import datetime



class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "user"

    __table_args__ = (
        Index("username_UNIQUE", "username"),
        Index("phone_UNIQUE", "phone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="用户名")
    password: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码(加密存储)")
    nickname: Mapped[Optional[str]] = mapped_column(String(50), comment="昵称")
    avatar: Mapped[Optional[str]] = mapped_column(String(255),  comment="头像URL",default="https://ts1.tc.mm.bing.net/th/id/OIP-C.jhFOy_KqHU3ZTzaKfK8YVgHaHa?w=193&h=193&c=8&rs=1&qlt=90&o=6&dpr=1.3&pid=ImgAns&rm=2")
    gender: Mapped[Optional[str]] = mapped_column(Enum("male", "female", "unknown"), comment="性别")
    bio: Mapped[Optional[str]] = mapped_column(String(500), comment="个人简介",default="这个人很懒，什么都没留下")
    phone: Mapped[Optional[str]] = mapped_column(String(11), comment="手机号")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def __repr__(self):
        return f"User(id={self.id}, username={self.username}, nickname={self.nickname})"



class UserToken(Base):
    __tablename__ = "user_token"
    # 用户令牌表

    __table_args__ = (
        Index("token_UNIQUE", "token"),
        Index("fk_user_token_user_idx", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="用户令牌ID")
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="用户令牌")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey(User.id), nullable=False, comment="用户ID")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="过期时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    

    def __repr__(self):
        return f"UserToken(id={self.id}, token={self.token}, user_id={self.user_id})"













