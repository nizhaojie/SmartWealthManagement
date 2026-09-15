from collections.abc import Iterator

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from app.db.migrate import apply_schema
from app.db.seed import seed
from app.db.session import get_session
from app.exceptions import AppError
from app.http import ok
from app.main import app
from app.redis_client import get_redis
from app.settings import get_settings


class ProbeIn(BaseModel):
    name: str


@app.get("/api/__test__/business-error")
def _business_error():
    raise AppError(1002, "知识库检索无结果")


@app.get("/api/__test__/system-error")
def _system_error():
    raise RuntimeError("secret stack boom")


@app.post("/api/__test__/validate")
def _validate(body: ProbeIn):
    return ok({"name": body.name})


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def _test_database_ready() -> None:
    settings = get_settings()
    apply_schema(settings.test_database_url)
    seed(settings.test_database_url)


@pytest.fixture
def auth_client(_test_database_ready: None) -> Iterator[TestClient]:
    settings = get_settings()
    test_engine = create_engine(settings.test_database_url)
    test_redis = redis_lib.Redis.from_url(settings.test_redis_url, decode_responses=True)
    test_redis.flushdb()

    def override_get_session() -> Iterator[OrmSession]:
        with OrmSession(test_engine) as session:
            yield session

    def override_get_redis() -> Iterator[redis_lib.Redis]:
        yield test_redis

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = override_get_redis
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_redis, None)
        test_redis.close()
        test_engine.dispose()
