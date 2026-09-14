from typing import Any

from fastapi.responses import JSONResponse

from app.tracing import get_trace_id

SUCCESS_CODE = 200
SUCCESS_MESSAGE = "success"


def envelope(code: int, message: str, data: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": get_trace_id(),
    }


def ok(data: Any = None, message: str = SUCCESS_MESSAGE) -> JSONResponse:
    return JSONResponse(status_code=200, content=envelope(SUCCESS_CODE, message, data))


def fail(code: int, message: str, data: Any = None, status_code: int | None = None) -> JSONResponse:
    http_status = status_code if status_code is not None else _http_status_for(code)
    return JSONResponse(status_code=http_status, content=envelope(code, message, data))


def _http_status_for(code: int) -> int:
    if code in {400, 401, 403, 404, 500}:
        return code
    return 200
