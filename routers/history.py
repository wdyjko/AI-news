from fastapi import APIRouter,Depends,Query,status,HTTPException
from crud import history
from schemas.history import HistoryAddRequest, HistoryListResponse
from sqlalchemy.ext.asyncio import AsyncSession
from models.users import User
from utils.auth import get_current_user
from utils.response import sucess_response
from config.db_conf import get_db
from schemas.history import HistoryNewsItemResponse



router = APIRouter(prefix="/api/history",tags=["history"])


@router.post("/add")
async def add_history(
    data: HistoryAddRequest,
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user)
    ):
    # 添加历史记录
    
    data = await history.add_news_history(db, user.id, data.news_id)
    return sucess_response(message='添加成功',data=data)



@router.get("/list")
async def get_history_list(
    page:int = Query(1,description="页码"),
    page_size:int = Query(10,description="每页数量"),
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user)
    ):
    # 获取历史记录列表
    rows,total = await history.get_history_list(db, user.id, page, page_size)

    history_list = []
    for news, view_time in rows:
        news_dict = {**news.__dict__, "viewTime": view_time}
        history_list.append(HistoryNewsItemResponse.model_validate(news_dict))


    has_more = total > page * page_size
    data = HistoryListResponse(list=history_list,total=total,hasMore=has_more)
    return sucess_response(message='获取成功',data=data)



@router.delete("/delete/{news_id}")
async def delete_history(
    news_id: int,
    user:User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 删除历史记录
    result = await history.remove_history(db, user.id, news_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该记录")
    return sucess_response(message='删除成功')



@router.delete("/clear")
async def clear_history(
    db: AsyncSession = Depends(get_db),
    user:User = Depends(get_current_user)
):
    # 清空用户历史记录
    count = await history.clear_history(db,user.id)
    return sucess_response(message=f'清空历史记录成功，共删除{count}条记录')










