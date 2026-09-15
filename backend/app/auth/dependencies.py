from collections.abc import Callable

import redis
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.auth.session_store import session_exists
from app.auth.tokens import ACCESS_TYPE, TokenAudienceMismatch, TokenError, decode_token
from app.db.models import Employee
from app.db.session import get_session
from app.exceptions import AppError
from app.redis_client import get_redis
from app.settings import Settings, get_settings

UNAUTHENTICATED_MESSAGE = "未认证"
INVALID_TOKEN_MESSAGE = "凭证无效或已过期"
DOMAIN_MISMATCH_MESSAGE = "身份域不匹配"
ROLE_FORBIDDEN_MESSAGE = "无权限"
EMPLOYEE_NOT_FOUND_MESSAGE = "员工不存在"


class AuthContext:
    def __init__(self, subject_id: int, session_id: str):
        self.subject_id = subject_id
        self.session_id = session_id


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, UNAUTHENTICATED_MESSAGE)
    return authorization.split(" ", 1)[1].strip()


def _build_dependency(get_audience: Callable[[Settings], str]) -> Callable[..., AuthContext]:
    def dependency(
        authorization: str | None = Header(default=None),
        cache: redis.Redis = Depends(get_redis),
        settings: Settings = Depends(get_settings),
    ) -> AuthContext:
        token = _extract_bearer_token(authorization)
        audience = get_audience(settings)
        try:
            payload = decode_token(
                token, audience=audience, expected_type=ACCESS_TYPE, settings=settings
            )
        except TokenAudienceMismatch as exc:
            raise AppError(403, DOMAIN_MISMATCH_MESSAGE) from exc
        except TokenError as exc:
            raise AppError(401, INVALID_TOKEN_MESSAGE) from exc

        session_id = payload["sid"]
        if not session_exists(cache, session_id):
            raise AppError(401, INVALID_TOKEN_MESSAGE)

        return AuthContext(subject_id=int(payload["sub"]), session_id=session_id)

    return dependency


require_customer = _build_dependency(lambda settings: settings.customer_token_audience)
require_internal = _build_dependency(lambda settings: settings.internal_token_audience)


def current_employee(
    auth: AuthContext = Depends(require_internal), db: Session = Depends(get_session)
) -> Employee:
    employee = db.get(Employee, auth.subject_id)
    if employee is None:
        raise AppError(401, EMPLOYEE_NOT_FOUND_MESSAGE)
    return employee


def require_employee_role(*roles: str) -> Callable[..., Employee]:
    allowed = set(roles)

    def dependency(employee: Employee = Depends(current_employee)) -> Employee:
        if employee.employee_role not in allowed:
            raise AppError(403, ROLE_FORBIDDEN_MESSAGE)
        return employee

    return dependency
