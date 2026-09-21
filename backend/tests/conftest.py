import logging
from collections.abc import Iterator

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.migrate import apply_schema
from app.db.models import KnowledgeMeta
from app.db.seed import seed
from app.db.session import get_session
from app.exceptions import AppError
from app.http import ok
from app.knowledge.service import STATUS_ACTIVE
from app.knowledge.vector_store import get_client
from app.main import app
from app.redis_client import get_redis
from app.settings import get_settings

logger = logging.getLogger("app.knowledge")

# Milvus 一次查询/删除涉及的标识上限；分块标识按这个粒度分批删。
_VECTOR_PRUNE_BATCH = 50


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


def _prune_rows_without_a_document() -> int:
    """按测试库的权威状态清掉向量库里已经没有文档的分块，返回清掉的文档数。

    测试库与向量库都跨运行持久，而**已下架文档的分块是产品接口删不掉的**：
    `delete_document` 对 expired 的文档直接 404，于是一次中断的运行（或者历史上某版
    删除逻辑）留下的分块会永远留在集合里。它们的正文与这一轮上传的探针文本逐字相同、
    相似度都是 1.0，于是 top-k 的名额被这些「已经没有文档的分块」占满；而它们在结果
    装配时又会被状态过滤掉——表现就是「刚上传的文档检索不到」，看着像检索坏了，
    其实是测试集合被历史残留污染。

    文档在、状态是 active 的分块一律保留，其余（文档已下架或元数据早已不在）删掉。
    只动 `test_milvus_collection`，演示用的那个集合不碰。
    """
    settings = get_settings()
    client = get_client(settings)
    collection = settings.test_milvus_collection
    if not client.has_collection(collection):
        return 0

    engine = create_engine(settings.test_database_url)
    try:
        with OrmSession(engine) as session:
            active_ids = set(
                session.scalars(
                    select(KnowledgeMeta.id).where(KnowledgeMeta.status == STATUS_ACTIVE)
                )
            )
    finally:
        engine.dispose()

    present = {
        int(row["knowledge_id"])
        for row in client.query(
            collection,
            filter="knowledge_id > 0",
            output_fields=["knowledge_id"],
            limit=16384,
        )
    }
    stale = sorted(present - active_ids)
    for start in range(0, len(stale), _VECTOR_PRUNE_BATCH):
        batch = stale[start : start + _VECTOR_PRUNE_BATCH]
        client.delete(
            collection, filter="knowledge_id in [" + ", ".join(map(str, batch)) + "]"
        )
    return len(stale)


@pytest.fixture(scope="session", autouse=True)
def _test_vector_store_aligned(_test_database_ready: None) -> None:
    """会话开始时把测试向量库对齐到测试库，见 `_prune_rows_without_a_document`。

    向量库不可用只记日志、不拦会话：需要它的用例自己会以连接失败暴露问题，而那之前
    的用例（种子、风控、适当性等）本就不该被牵连。
    """
    try:
        removed = _prune_rows_without_a_document()
    except Exception:  # noqa: BLE001 - 对齐是卫生工作，不该让整个会话起不来
        logger.warning("测试向量库对齐失败，跳过", exc_info=True)
        return
    if removed:
        logger.warning("测试向量库清理了 %s 个已无文档的分块", removed)


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
