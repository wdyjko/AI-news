from sqlalchemy import Integer, ForeignKey, DateTime
from sqlalchemy.orm import mapped_column,DeclarativeBase,Mapped
from datetime import datetime
from models.news import News
from models.users import User
from sqlalchemy import Index, UniqueConstraint



class Base(DeclarativeBase):
    pass



class History(Base):
    """
    历史记录表ORM模型
    """
    __tablename__='history'

    # 创建索引
    __table_args__=(
    UniqueConstraint('user_id','news_id',name='user_news_unique'),
    Index('fk_history_user_idx','user_id'),
    Index('fk_history_news_idx','news_id'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="历史记录ID")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey(User.id), nullable=False, comment="用户ID")
    news_id: Mapped[int] = mapped_column(Integer, ForeignKey(News.id), nullable=False, comment="新闻ID")
    view_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False, comment="查看时间")

    def __repr__(self):
        return f"<History(id={self.id}, user_id={self.user_id}, news_id={self.news_id}, view_time={self.view_time})>"




