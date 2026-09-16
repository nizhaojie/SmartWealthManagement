import json
import logging
from collections.abc import Generator

import redis
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from neo4j import Driver
from sqlalchemy.orm import Session

from app.agent.graph import run_customer_service_turn
from app.agent.schemas import ChatRequest, ChatResponse, CitationResponse
from app.auth.dependencies import AuthContext, require_customer
from app.db.session import get_session
from app.http import ok
from app.neo4j_client import get_neo4j
from app.redis_client import get_redis
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/customer/chat")

logger = logging.getLogger("app")

SSE_MEDIA_TYPE = "text/event-stream"


def _run_turn(
    body: ChatRequest,
    db: Session,
    cache: redis.Redis,
    settings: Settings,
    auth: AuthContext,
    driver: Driver,
) -> ChatResponse:
    result = run_customer_service_turn(
        db,
        cache,
        settings,
        driver=driver,
        session_id=auth.session_id,
        user_id=auth.subject_id,
        question=body.message,
    )
    return ChatResponse(
        answer=result.answer,
        citations=[
            CitationResponse.model_validate(citation, from_attributes=True)
            for citation in result.citations
        ],
        intent=result.intent,
        content_classification=result.content_classification,
    )


@router.post("/messages")
def send_message(
    body: ChatRequest,
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    auth: AuthContext = Depends(require_customer),
    driver: Driver = Depends(get_neo4j),
):
    return ok(_run_turn(body, db, cache, settings, auth, driver).model_dump())


def _sse_frame(data: dict, *, event: str | None = None) -> str:
    lines = [f"event: {event}"] if event else []
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _stream_chat_response(response: ChatResponse) -> Generator[str, None, None]:
    # 兜底判断、引用剔除、内容分类在调用方已经全部完成——这里只把定案的
    # 回答逐字转成传输帧，推流过程本身不再做任何决策。
    try:
        for character in response.answer:
            yield _sse_frame({"delta": character})
        yield _sse_frame(response.model_dump(), event="done")
    except Exception:
        logger.exception("SSE 推流中断")


@router.post("/stream")
def stream_message(
    body: ChatRequest,
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    auth: AuthContext = Depends(require_customer),
    driver: Driver = Depends(get_neo4j),
):
    response = _run_turn(body, db, cache, settings, auth, driver)
    return StreamingResponse(_stream_chat_response(response), media_type=SSE_MEDIA_TYPE)
