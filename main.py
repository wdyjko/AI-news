from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

from utils.exeception_handlers import register_exception_handlers
register_exception_handlers(app)



from routers.favorite import router
app.include_router(router)

from routers.history import router
app.include_router(router)



from routers.news import router
app.include_router(router)


from routers.user import router
app.include_router(router)


# AI 摘要相关接口（流式 / 批量 / 指标）
from routers.ai import router as ai_router
app.include_router(ai_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # 允许所有来源访问,实际项目中建议指定具体的来源
    allow_credentials=True,    # 允许携带凭证（如cookies）
    allow_methods=["*"],      # 允许所有HTTP请求方法
    allow_headers=["*"],      # 允许所有请求头
)







@app.get("/")
async def root():
    return {"Hello": "World"}