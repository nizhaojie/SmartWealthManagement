"""验证 `graph_demo_seed` 叠加基础种子后，图谱规模满足验收要求
（节点数 > 100，关系数 > 200，见 issue 01 的 Further Notes）。

`app.db.seed.seed()` 的基础夹具只有 5 个客户、7 个产品，规模不够，也不能
为了凑数改动它——很多用例按精确数字断言。这里改用一个独立的 scratch
MySQL 库跑「基础种子 + 演示叠加种子」，跑在真实容器上，比其它用例慢，
单独成文件方便按需跳过，也不会污染 `wealth_test`。
"""

import pytest
from neo4j import GraphDatabase
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as OrmSession

from app.db.graph_demo_seed import seed_graph_demo
from app.db.migrate import apply_schema
from app.db.seed import seed
from app.knowledge_graph import sync
from app.settings import get_settings

_SCRATCH_DB = "wealth_graph_demo_scale_test"
_NAMESPACE = "wealth_graph_demo_scale_test"


@pytest.fixture(scope="module")
def scratch_database_url():
    settings = get_settings()
    root_engine = create_engine(settings.mysql_root_url)
    with root_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {_SCRATCH_DB}"))
        conn.execute(text(f"CREATE DATABASE {_SCRATCH_DB}"))
        conn.execute(text(f"GRANT ALL PRIVILEGES ON {_SCRATCH_DB}.* TO 'wealth_app'@'%'"))
        conn.execute(text("FLUSH PRIVILEGES"))
        conn.commit()
    root_engine.dispose()

    url = settings.database_url.rsplit("/", 1)[0] + f"/{_SCRATCH_DB}"
    yield url

    root_engine = create_engine(settings.mysql_root_url)
    with root_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {_SCRATCH_DB}"))
        conn.commit()
    root_engine.dispose()


def test_demo_scale_meets_acceptance_threshold(scratch_database_url):
    apply_schema(scratch_database_url)
    seed(scratch_database_url)
    seed_graph_demo(scratch_database_url)

    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    engine = create_engine(scratch_database_url)
    try:
        with OrmSession(engine) as db:
            stats = sync.rebuild_graph(db, driver, namespace=_NAMESPACE)
        with driver.session() as session:
            session.run("MATCH (n {namespace: $ns}) DETACH DELETE n", ns=_NAMESPACE)
    finally:
        driver.close()
        engine.dispose()

    assert stats["node_count"] > 100
    assert stats["relationship_count"] > 200
