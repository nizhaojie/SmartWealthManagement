import json
from datetime import timedelta

import redis

_PREFIX = "auth:session:"


def _key(session_id: str) -> str:
    return f"{_PREFIX}{session_id}"


def create_session(
    client: redis.Redis,
    *,
    session_id: str,
    domain: str,
    subject_id: int,
    username: str,
    ttl: timedelta,
) -> None:
    client.set(
        _key(session_id),
        json.dumps({"domain": domain, "subject_id": subject_id, "username": username}),
        ex=ttl,
    )


def session_exists(client: redis.Redis, session_id: str) -> bool:
    return bool(client.exists(_key(session_id)))


def delete_session(client: redis.Redis, session_id: str) -> None:
    client.delete(_key(session_id))
