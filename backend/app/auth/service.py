from datetime import timedelta
from typing import Any
from uuid import uuid4

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import verify_password
from app.auth.session_store import create_session, delete_session, session_exists
from app.auth.tokens import (
    REFRESH_TYPE,
    TokenAudienceMismatch,
    TokenError,
    decode_token,
    issue_access_token,
    issue_refresh_token,
)
from app.db.models import Customer, Employee
from app.exceptions import AppError
from app.settings import Settings, get_settings

INVALID_CREDENTIALS_MESSAGE = "账号或密码错误"
INVALID_REFRESH_MESSAGE = "刷新凭证无效或已过期"

Credentialed = Customer | Employee


def authenticate(db: Session, model: Any, username: str, password: str) -> Credentialed:
    user = db.scalar(select(model).where(model.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise AppError(401, INVALID_CREDENTIALS_MESSAGE)
    return user  # type: ignore[no-any-return]


def _issue_session(
    db: Session,
    cache: redis.Redis,
    *,
    model: Any,
    domain: str,
    audience: str,
    username: str,
    password: str,
    settings: Settings,
) -> tuple[str, str]:
    user = authenticate(db, model, username, password)
    session_id = str(uuid4())
    create_session(
        cache,
        session_id=session_id,
        domain=domain,
        subject_id=user.id,
        username=user.username,
        ttl=timedelta(days=settings.refresh_token_expire_days),
    )
    access = issue_access_token(
        subject=str(user.id), audience=audience, session_id=session_id, settings=settings
    )
    refresh = issue_refresh_token(
        subject=str(user.id), audience=audience, session_id=session_id, settings=settings
    )
    return access, refresh


def login_customer(
    db: Session,
    cache: redis.Redis,
    *,
    username: str,
    password: str,
    settings: Settings | None = None,
) -> tuple[str, str]:
    settings = settings or get_settings()
    return _issue_session(
        db,
        cache,
        model=Customer,
        domain="customer",
        audience=settings.customer_token_audience,
        username=username,
        password=password,
        settings=settings,
    )


def login_employee(
    db: Session,
    cache: redis.Redis,
    *,
    username: str,
    password: str,
    settings: Settings | None = None,
) -> tuple[str, str]:
    settings = settings or get_settings()
    return _issue_session(
        db,
        cache,
        model=Employee,
        domain="employee",
        audience=settings.internal_token_audience,
        username=username,
        password=password,
        settings=settings,
    )


def _refresh_access_token(
    cache: redis.Redis, *, audience: str, refresh_token: str, settings: Settings
) -> str:
    try:
        payload = decode_token(
            refresh_token, audience=audience, expected_type=REFRESH_TYPE, settings=settings
        )
    except TokenAudienceMismatch as exc:
        raise AppError(403, INVALID_REFRESH_MESSAGE) from exc
    except TokenError as exc:
        raise AppError(401, INVALID_REFRESH_MESSAGE) from exc

    session_id = payload["sid"]
    if not session_exists(cache, session_id):
        raise AppError(401, INVALID_REFRESH_MESSAGE)

    return issue_access_token(
        subject=payload["sub"], audience=audience, session_id=session_id, settings=settings
    )


def refresh_customer_access_token(
    cache: redis.Redis, *, refresh_token: str, settings: Settings | None = None
) -> str:
    settings = settings or get_settings()
    return _refresh_access_token(
        cache, audience=settings.customer_token_audience, refresh_token=refresh_token, settings=settings
    )


def refresh_employee_access_token(
    cache: redis.Redis, *, refresh_token: str, settings: Settings | None = None
) -> str:
    settings = settings or get_settings()
    return _refresh_access_token(
        cache, audience=settings.internal_token_audience, refresh_token=refresh_token, settings=settings
    )


def logout(cache: redis.Redis, session_id: str) -> None:
    delete_session(cache, session_id)
