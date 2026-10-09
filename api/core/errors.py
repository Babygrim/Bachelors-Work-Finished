from enum import StrEnum
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    USER_EXISTS = "USER_EXISTS"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    INVALID_TOKEN = "INVALID_TOKEN"
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
    UNSUPPORTED_SCALE = "UNSUPPORTED_SCALE"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    VIDEO_UPSCALING_NOT_IMPLEMENTED = "VIDEO_UPSCALING_NOT_IMPLEMENTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        reason: str,
        status_code: int = 400,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason
        self.status_code = status_code
        self.details = details


def error_payload(error: AppError) -> dict[str, Any]:
    result = {
        "error": {
            "code": error.code,
            "message": error.message,
            "reason": error.reason,
        }
    }
    if error.details is not None:
        result["error"]["details"] = error.details
    return result


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, error: AppError) -> JSONResponse:
        return JSONResponse(error.status_code, error_payload(error))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
        validation = AppError(
            ErrorCode.VALIDATION_ERROR,
            "The request could not be validated.",
            "One or more fields have an invalid value.",
            422,
            error.errors(),
        )
        return JSONResponse(422, error_payload(validation))

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, error: HTTPException) -> JSONResponse:
        wrapped = AppError(
            ErrorCode.INVALID_REQUEST,
            "The request could not be completed.",
            str(error.detail),
            error.status_code,
        )
        return JSONResponse(error.status_code, error_payload(wrapped))

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, error: Exception) -> JSONResponse:
        wrapped = AppError(
            ErrorCode.INTERNAL_ERROR,
            "The server could not complete the request.",
            str(error),
            500,
        )
        return JSONResponse(500, error_payload(wrapped))
