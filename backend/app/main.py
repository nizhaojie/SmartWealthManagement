import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.advisory import customer_router as advisory_customer_router
from app.api.advisory import router as advisory_router
from app.api.advisory_request import internal_router as advisory_request_internal_router
from app.api.advisory_request import router as advisory_request_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.customer_assets import internal_router as customer_assets_internal_router
from app.api.customer_assets import router as customer_assets_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.customer_profile import internal_router as customer_profile_internal_router
from app.api.customer_profile import router as customer_profile_router
from app.api.risk_assessment import internal_router as risk_assessment_internal_router
from app.api.risk_assessment import router as risk_assessment_router
from app.api.products import router as products_router
from app.api.suitability import internal_router as suitability_internal_router
from app.api.suitability import router as suitability_router
from app.exceptions import AppError
from app.http import fail
from app.logging_setup import setup_logging
from app.tracing import bind_trace_id, get_trace_id

setup_logging()
logger = logging.getLogger("app")


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_map = {key: value for key, value in scope.get("headers", [])}
        incoming = header_map.get(b"x-trace-id")
        bind_trace_id(incoming.decode() if incoming else None)
        logger.info("%s %s", scope.get("method"), scope.get("path"))

        async def send_with_trace(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-trace-id", get_trace_id().encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_trace)


app = FastAPI(title="智能财富管家系统")
app.add_middleware(TraceIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def handle_app_error(_request: Request, exc: AppError):
    logger.info("business error %s", exc.code)
    return fail(exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request: Request, _exc: RequestValidationError):
    logger.info("validation error")
    return fail(400, "参数错误")


HTTP_MESSAGES = {
    400: "参数错误",
    401: "未认证",
    403: "无权限",
    404: "资源不存在",
    500: "服务内部错误",
}


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_request: Request, exc: StarletteHTTPException):
    code = exc.status_code if exc.status_code in HTTP_MESSAGES else 500
    logger.info("http error %s", code)
    return fail(code, HTTP_MESSAGES[code])


@app.exception_handler(Exception)
async def handle_uncaught_error(_request: Request, _exc: Exception):
    logger.exception("unhandled error")
    return fail(500, "服务内部错误")


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(knowledge_router)
app.include_router(chat_router)
app.include_router(risk_assessment_router)
app.include_router(risk_assessment_internal_router)
app.include_router(customer_profile_router)
app.include_router(customer_profile_internal_router)
app.include_router(suitability_router)
app.include_router(suitability_internal_router)
app.include_router(products_router)
app.include_router(customer_assets_router)
app.include_router(customer_assets_internal_router)
app.include_router(advisory_request_router)
app.include_router(advisory_request_internal_router)
app.include_router(analytics_router)
app.include_router(advisory_router)
app.include_router(advisory_customer_router)
app.include_router(graph_router)
