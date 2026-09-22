"""golden 问答集与两条兜底阈值的回归（`rag-retrieval-upgrade` 04，ADR-0022 决定 6）。

三个 seam：

- **纯函数 / 语料自洽**：golden 集里的正例必须真的能在 `rag_db/` 语料里找到
  （`source_file` 存在、`snippet` 在其中）。语料改了而 golden 集没跟上时，校准量的
  就是别的东西，这一类断言要先把这件事拦下来。
- **检索链路的相对关系（fake embedding）**：默认测试没有 key，fake embedding 给出的
  余弦与真实模型无关，所以这里**只钉相对关系**——正例声明的目标确实进了候选池、默认
  阈值下「正例的达标率高于负例、负例不达标」、关键词臂的正负例分布不重叠——**不钉
  绝对值**。绝对数值由 `scripts/calibrate_retrieval.py` 在真实 embedding 下产出，
  人工复核后写回 `Settings`。
- **后端 HTTP 层**：一条明显无关的问题（取自 golden 的负例）必须走兜底话术、
  不发起生成——这是 S2 口径在整条链路上的复述。

关键词那一侧的量纲与 embedding 无关，因此它的默认阈值在这里是**有意义**的、可以直接
断言「负例不达标」；余弦那一侧不能——这正是「绝对数值不能进 CI」的出处。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

import app.agent.graph as agent_graph
from app.agent.graph import has_retrieval_evidence
from app.db.models import KnowledgeMeta
from app.knowledge.seed_rag_db import RAG_DB_DIR, seed_rag_db, source_files
from app.knowledge.service import STATUS_ACTIVE, delete_document
from app.main import app
from app.settings import Settings, get_settings
from scripts.calibrate_retrieval import (
    NEGATIVE_KIND,
    GoldenRun,
    collect_runs,
    load_golden,
    suggest_thresholds,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "retrieval_golden.json"

CUSTOMER_USERNAME = "wangc1"
SEEDED_PASSWORD = "Test@1234"

UNUSED_GRAPH_NAMESPACE = "wealth_test_retrieval_calibration_unused"


def _rag_db_source_files() -> list[str]:
    return [path.relative_to(RAG_DB_DIR).as_posix() for path in source_files()]


def _base_settings() -> Settings:
    """不读 `backend/.env`：本文件钉的是 `app/settings.py` 里的**代码默认值**。

    `.env` 是个人环境覆盖，本地开发机器上可能有历史遗留的阈值；读它会让这条回归
    时而检查代码、时而检查某个人的机器。环境变量仍然生效（CI 用它们注入数据库地址）。
    """
    return Settings(_env_file=None)


def _seeded_settings() -> Settings:
    base = _base_settings()
    return base.model_copy(
        update={
            "database_url": base.test_database_url,
            "milvus_collection": base.test_milvus_collection,
            # 没有 key 即 fake embedding / fake LLM：确定性、不发外呼（回放之外的
            # 另一条离线路径）。这里不覆盖两条阈值——回归要钉的正是默认值。
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": UNUSED_GRAPH_NAMESPACE,
        }
    )


def _active_corpus(settings: Settings) -> list[KnowledgeMeta]:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(
                    select(KnowledgeMeta)
                    .where(KnowledgeMeta.source_file.in_(_rag_db_source_files()))
                    .where(KnowledgeMeta.status == STATUS_ACTIVE)
                )
            )
    finally:
        engine.dispose()


def _drop_corpus(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as session:
            for meta in _active_corpus(settings):
                delete_document(session, settings, meta.id)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def seeded_corpus() -> Iterator[Settings]:
    """seed 一遍 `rag_db/`，用完把这一批文档下架（与 `test_seed_rag_db` 同一口径）。

    测试库是所有用例共用的：这九份真实语料留在库里会改变其他用例的检索排序。
    本文件要验证的是「语料 + golden 集 + 两条阈值」的关系，验完还原。
    """
    settings = _seeded_settings()
    seed_rag_db(settings)
    try:
        yield settings
    finally:
        _drop_corpus(settings)


@pytest.fixture
def chat_client(auth_client: TestClient, seeded_corpus: Settings) -> Iterator[TestClient]:
    """聊天接口跑在测试库 + 测试向量集合上，且用的是上面那份 seeded 语料。"""
    app.dependency_overrides[get_settings] = lambda: seeded_corpus
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _run_golden(settings: Settings) -> list[GoldenRun]:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as session:
            return collect_runs(
                session,
                settings,
                load_golden(GOLDEN_PATH),
                top_k=settings.hybrid_recall_top_k,
            )
    finally:
        engine.dispose()


def _customer_login(client: TestClient) -> str:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


# --- golden 集自身的形状与语料自洽 ---


def test_golden_set_covers_the_three_positive_kinds_with_negatives():
    golden = load_golden(GOLDEN_PATH)

    assert {item["kind"] for item in golden["positives"]} == {
        "literal",
        "semantic",
        "faq",
    }, "三类正例各要有一条：字面型、语义型、FAQ 按对拆分后的问题"
    assert golden["negatives"], "负例是噪声基线的来源，不能为空"
    for item in golden["positives"]:
        assert item["source_file"], f"{item['id']} 缺 source_file"
        assert item["snippet"], f"{item['id']} 缺 snippet"

    ids = [item["id"] for item in (*golden["positives"], *golden["negatives"])]
    assert len(ids) == len(set(ids)), "id 必须唯一"


def test_every_positive_target_exists_in_the_rag_db_corpus():
    golden = load_golden(GOLDEN_PATH)

    for item in golden["positives"]:
        path = RAG_DB_DIR / item["source_file"]
        assert path.is_file(), f"{item['id']} 指向不存在的语料文件：{item['source_file']}"
        assert item["snippet"] in path.read_text(encoding="utf-8"), (
            f"{item['id']} 的 snippet 在 {item['source_file']} 里找不到——"
            "语料改了而 golden 集没跟上，校准量的就不是它声明的东西"
        )


# --- 检索链路：相对关系（fake embedding） ---


def test_literal_and_faq_positives_hit_their_declared_target(seeded_corpus: Settings):
    """字面型与 FAQ 正例声明的「期望命中」都要真的落到候选池里。

    上面那条只验 snippet 在源文件里**存在**；检索不到的话，golden 集就是在描述一份
    它自己都没命中的语料。只对字面型与 FAQ 断言：这两类靠逐字命中，与 embedding 无关，
    CI 里跑得出与线上同一个结论。语义型归向量臂，fake embedding 下它找不到自己的目标
    （实测 3 条语义正例都不进候选池）——那一条只能在真实 embedding 的校准运行里看。
    """
    runs = _run_golden(seeded_corpus)
    missed = [
        (run.question, run.kind)
        for run in runs
        if run.kind in ("literal", "faq") and not run.hit
    ]

    assert not missed, f"这些正例的期望分块没进候选池：{missed}"


def test_calibrated_thresholds_admit_positives_and_reject_negatives(
    seeded_corpus: Settings,
):
    """默认阈值下「正例达标率高于负例、负例不达标」——走生产的 `has_retrieval_evidence`。

    只看相对关系，不断言阈值或证据分的绝对值：fake embedding 的余弦与真实模型无关，
    拿它比余弦阈值没有意义。它仍然是一条有效的回归——`has_retrieval_evidence` 是
    「该不该作答」的唯一口径，负例一条都不该被它判成有依据。
    """
    runs = _run_golden(seeded_corpus)
    positives = [run for run in runs if run.kind != NEGATIVE_KIND]
    negatives = [run for run in runs if run.kind == NEGATIVE_KIND]

    def _has_evidence(run: GoldenRun) -> bool:
        return has_retrieval_evidence(
            {**run.evidence, "graph": 0.0},
            vector_threshold=seeded_corpus.retrieval_score_threshold,
            keyword_threshold=seeded_corpus.retrieval_keyword_score_threshold,
        )

    positive_rate = sum(1 for run in positives if _has_evidence(run)) / len(positives)
    negative_rate = sum(1 for run in negatives if _has_evidence(run)) / len(negatives)

    assert positive_rate > negative_rate, (
        f"正例达标率 {positive_rate} 必须高于负例 {negative_rate}"
        f"（向量阈值 {seeded_corpus.retrieval_score_threshold}、"
        f"关键词阈值 {seeded_corpus.retrieval_keyword_score_threshold}）"
    )
    assert negative_rate == 0.0, (
        "无关问题不该被判成有依据："
        f"{[(run.question, run.evidence) for run in negatives if _has_evidence(run)]}"
    )


def test_keyword_arm_positives_and_negatives_do_not_overlap(seeded_corpus: Settings):
    """keyword 臂上正例与负例的分布不重叠——校准因此存在一条可画的线。

    这条跑的是 `suggest_thresholds` 里的判断。**只对关键词臂断言**：BM25 不依赖
    embedding，它的分布在 CI 里与真实运行一致；向量臂在 fake embedding 下不成立——
    假 embedding 本质是字面哈希，语义型正例在它眼里的余弦可以低于一条偶然共享几个字
    的负例（实测正例最低 0.07、负例最高 0.21）。这正是「余弦的绝对数值只能由真实
    embedding 产出」的实证，也是它不能进 CI 的原因。

    断言的只有「可分离」这一条：建议值本身就是按这个间隔算出来的，再断言
    「正例 ≥ 建议值 > 负例」只是把自己的输出复述一遍。
    """
    runs = _run_golden(seeded_corpus)
    suggestion = next(
        item for item in suggest_thresholds(runs) if item.arm == "keyword"
    )

    assert suggestion.separable, suggestion.detail
    assert suggestion.value is not None


# --- HTTP 层：无关问题走兜底，不发起生成 ---


def test_an_unrelated_question_falls_back_without_generating(chat_client, monkeypatch):
    golden = load_golden(GOLDEN_PATH)
    question = golden["negatives"][0]["question"]

    def _fail(*_args, **_kwargs):
        raise AssertionError("没有依据时不应发起生成")

    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _fail)

    token = _customer_login(chat_client)
    response = chat_client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": question},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citations"] == []
    assert "95588" in data["answer"] or "人工客服" in data["answer"]
