from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.settings import Settings, get_settings

ACCESS_TYPE = "access"
REFRESH_TYPE = "refresh"


class TokenError(Exception):
    """Base for token decode failures."""


class TokenAudienceMismatch(TokenError):
    pass


class TokenInvalid(TokenError):
    pass


def _encode(payload: dict[str, Any], settings: Settings) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def issue_access_token(
    *, subject: str, audience: str, session_id: str, settings: Settings | None = None
) -> str:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "aud": audience,
        "sid": session_id,
        "type": ACCESS_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return _encode(payload, settings)


def issue_refresh_token(
    *, subject: str, audience: str, session_id: str, settings: Settings | None = None
) -> str:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "aud": audience,
        "sid": session_id,
        "type": REFRESH_TYPE,
        "iat": now,
        "exp": now + timedelta(days=settings.refresh_token_expire_days),
    }
    return _encode(payload, settings)


def decode_token(
    token: str, *, audience: str, expected_type: str, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=audience,
        )
    except jwt.InvalidAudienceError as exc:
        raise TokenAudienceMismatch(str(exc)) from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalid(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise TokenInvalid("unexpected token type")
    return payload
