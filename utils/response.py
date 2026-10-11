from fastapi.responses import JSONResponse,HTMLResponse
from fastapi.encoders import jsonable_encoder


def sucess_response(message:str = 'success',data=None):
    content = {
        "code": 200,
        "message": message,
        "data": data
    }
    # 目标：把任何fastapi，pydantic，orm对象都要正常响应--code,message,data
    return JSONResponse(content=jsonable_encoder(content))
