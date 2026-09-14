from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.exceptions import AppError
from app.http import ok
from app.main import app


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
