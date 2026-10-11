from fastapi import FastAPI, Request, HTTPException
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from utils.exception import  general_error_handler, http_exception_handler, sqlalchemy_error_handler, integrity_error_handler


def register_exception_handlers(app: FastAPI):
    """
    注册全局异常处理函数:子类在前，父类在后;具体在前，抽象在后
    """
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(Exception, general_error_handler)