import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.graph import run_customer_service_turn
from app.agent.schemas import ChatRequest, ChatResponse, CitationResponse
from app.auth.dependencies import AuthContext, require_customer
from app.db.session import get_session
from app.http import ok
from app.redis_client import get_redis
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/customer/chat")


@router.post("/messages")
def send_message(
    body: ChatRequest,
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    auth: AuthContext = Depends(require_customer),
):
    result = run_customer_service_turn(
        db,
        cache,
        settings,
        session_id=auth.session_id,
        user_id=auth.subject_id,
        question=body.message,
    )
    response = ChatResponse(
        answer=result.answer,
        citations=[
            CitationResponse.model_validate(citation, from_attributes=True)
            for citation in result.citations
        ],
        intent=result.intent,
        content_classification=result.content_classification,
    )
    return ok(response.model_dump())
