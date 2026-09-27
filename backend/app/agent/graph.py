import time
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict, cast

import redis
from langgraph.graph import END, StateGraph
from neo4j import Driver
from sqlalchemy.orm import Session

from app import degradation
from app.agent import archive, debug_trace, memory
from app.agent.citations import Citation, reconcile_answer
from app.agent.config import CUSTOMER_SERVICE_CONFIG, CUSTOMER_SERVICE_VIEW_NAMES
from app.agent.fusion import fuse_and_rank
from app.agent.intent import RETRIEVAL_INTENTS, Intent, classify_intent
from app.agent.risk_intent import detect_risk_intent
from app.agent.schemas import DataAnswerColumn, DataAnswerResponse
from app.analytics import catalog
from app.analytics.audience import Audience
from app.analytics.errors import OUT_OF_SCOPE_CODE, QUERY_TIMEOUT_CODE
from app.analytics.execution import QueryResult
from app.analytics.graph import AnalyticsState
from app.analytics.service import run_restricted_query
from app.db.analytics_account import AnalyticsIdentity
from app.event_bus import (
    EVENT_RISK_INTENT_DETECTED,
    SOURCE_CUSTOMER_SERVICE,
    Event,
    EventPublisher,
    publish_safely,
)
from app.exceptions import AppError
from app.knowledge.hybrid import carried_evidence
from app.knowledge.rerank import rerank_chunks
from app.knowledge.service import ChunkResult, search_chunks
from app.knowledge_graph.graphrag import (
    DEGRADED_NO_ENTITY,
    DEGRADED_TIMEOUT,
    DEPENDENCY_DEGRADATION_REASONS,
    GraphAugmentation,
    GraphPassage,
    PassageEntityType,
    augment_with_graph,
)
from app.replay import library as replay_library
from app.llm.provider import (
    build_chitchat_messages,
    build_grounded_messages,
    generate_chitchat_reply,
    generate_grounded_answer,
    model_failure_answer,
)
from app.settings import Settings
from app.tracing import get_token_usage, get_trace_id, start_token_usage


def fallback_message(settings: Settings) -> str:
    return (
        "很抱歉，我在知识库里没有找到能支撑这个问题的依据，不想给您一个没有出处的答案。"
        f"建议您拨打人工客服热线 {settings.human_service_channel} 由人工为您核实。"
    )


def handoff_message(settings: Settings) -> str:
    return f"已为您转接人工客服，请拨打 {settings.human_service_channel}，会有专属客服为您处理。"


# ---- 客户的数据查询分支（ADR-0025）--------------------------------------------
#
# 数据查询有三条出口，话术彼此必须可区分，且**都不回退到知识检索**：失败/超时是
# 降级（明说查不了、写降级留痕），白名单外是边界（告诉客户能查什么），零行是事实
# （如实说没有）。拿知识库里的泛泛之谈冒充数据答案是危险形态，因此这里没有兜底一问。

DATA_QUERY_FAILURE_MESSAGE = (
    "很抱歉，您的数据我暂时查不了。请稍后再试，或到资产页查看。"
)
DATA_QUERY_EMPTY_MESSAGE = "没有查到符合条件的数据。"


def data_query_out_of_scope_message() -> str:
    """白名单外的话术：说清不在可查范围，并把可查的东西列出来。

    清单由视图目录生成（``catalog.queryable_topics``），不在这里另抄一遍白名单——
    抄一遍，白名单改了话术就会撒谎。
    """
    topics = "、".join(catalog.queryable_topics(CUSTOMER_SERVICE_VIEW_NAMES))
    return (
        f"这个问题不在我能查询的范围内。我可以帮您查的是：{topics}。"
        "您可以换个问法问问自己名下的数据。"
    )


@dataclass
class DataQueryTurn:
    """数据查询分支的一条回答，以及这一轮查询的留痕材料。"""

    answer: str
    # 生成的查询、命中的视图、行数与业务错误码。交给客服回合写进调试级留痕
    # （30 天），不写进工具调用：数据查询是一类分支而不是一个工具（ADR-0025），
    # 记成工具调用会让「这个 Agent 有什么工具」与它实际做的事对不上。
    material: dict
    # 面向客户的结构化结果（ADR-0028）：只有「有行」这条出口才带它。SQL 与
    # `customer_id` 不进这里——它是客户契约，不是留痕材料的另一种排布。
    data_answer: DataAnswerResponse | None = None


# 不进客户契约的列（ADR-0028）。它是行级范围机制的内部标识：裁剪发生在后端这一步，
# 不靠前端隐藏列——前端隐藏是「看不见但已经送达」，那正是这条纪律要避免的形态。
_CUSTOMER_HIDDEN_COLUMNS = frozenset({"customer_id"})


def customer_data_answer(
    views: list[catalog.ViewSpec], result: QueryResult
) -> DataAnswerResponse:
    """把一次「有行」的查询整理成面向客户的结果表（ADR-0028）。

    - 表头取视图目录里的中文标签，缺标签回落列名（不丢列）；
    - `customer_id` 在这一步剔除，`views` 给中文名而不是 `va_*` 视图名；
    - SQL 从不进这里：它只进 30 天调试级留痕。

    它只被「有行」那条出口调用：零行、失败/超时、白名单外都不该长出一张空表。
    """
    labels: dict[str, str] = {}
    for view in views:
        for column, label in view.column_labels.items():
            labels.setdefault(column, label)
    kept = [
        index
        for index, column in enumerate(result.columns)
        if column not in _CUSTOMER_HIDDEN_COLUMNS
    ]
    return DataAnswerResponse(
        columns=[
            DataAnswerColumn(
                key=result.columns[index],
                label=labels.get(result.columns[index], result.columns[index]),
            )
            for index in kept
        ],
        rows=[[row[index] for index in kept] for row in result.rows],
        row_count=len(result.rows),
        truncated=result.truncated,
        # 视图的中文名：客户不认 `va_my_holdings`，而视图目录里本来就有它的中文名。
        views=[view.label or view.name for view in views],
    )


def answer_customer_data_question(
    db: Session,
    settings: Settings,
    *,
    customer_id: int,
    question: str,
    history: list[dict],
) -> DataQueryTurn:
    """把客户的一句数据问题跑成一条面向客户的文本（ADR-0025）。

    复用数据分析 Agent 的那条链路（选视图 → 生成 → 校验 → 执行 → 解读），只换
    两样：执行身份是凭证客户——客户域视图的行级条件因此锁死为本人；使用者口径是
    客户——解读说的是事实，不带评价。客户看到的文字进审计级留痕
    （``app.agent.archive``），查询本身的材料进调试级留痕。
    """
    final_state: AnalyticsState = run_restricted_query(
        db,
        settings,
        identity=AnalyticsIdentity.customer(customer_id=customer_id),
        question=question,
        history=history,
        view_names=CUSTOMER_SERVICE_VIEW_NAMES,
        audience=Audience.CUSTOMER,
    )
    material = _data_query_material(final_state)
    error_code = final_state.get("error_code")
    if error_code == OUT_OF_SCOPE_CODE:
        return DataQueryTurn(
            answer=data_query_out_of_scope_message(), material=material
        )
    if error_code is not None:
        _report_data_query_failure(db, error_code, final_state.get("error_message"))
        return DataQueryTurn(answer=DATA_QUERY_FAILURE_MESSAGE, material=material)
    if not final_state["result"].rows:
        return DataQueryTurn(answer=DATA_QUERY_EMPTY_MESSAGE, material=material)
    return DataQueryTurn(
        answer=final_state["interpretation"],
        material=material,
        data_answer=customer_data_answer(final_state["views"], final_state["result"]),
    )


def _data_query_material(final_state: AnalyticsState) -> dict:
    """这一轮数据查询的原始材料：走了哪条出口、查了什么、取回几行。"""
    result = final_state.get("result")
    return {
        "sql": final_state.get("sql"),
        "views": [view.name for view in final_state.get("views", [])],
        "row_count": len(result.rows) if result is not None else None,
        "truncated": result.truncated if result is not None else None,
        "error_code": final_state.get("error_code"),
    }


def _report_data_query_failure(
    db: Session, error_code: int, message: str | None
) -> None:
    """失败 / 超时留一条降级痕迹：客户察觉不到降级与正常的区别，统计要能察觉。"""
    degradation.record(
        db,
        dependency=degradation.DEPENDENCY_DATA_QUERY,
        reason=(
            degradation.REASON_TIMEOUT
            if error_code == QUERY_TIMEOUT_CODE
            else degradation.REASON_UNAVAILABLE
        ),
        agent_type=CUSTOMER_SERVICE_CONFIG.name,
        trace_id=get_trace_id(),
        detail=f"{error_code}: {message}",
    )


def report_model_failure(db: Session, exc: AppError) -> None:
    """模型调用彻底失败时留一条降级痕迹，然后由调用方给出预设兜底回答。"""
    degradation.record(
        db,
        dependency=degradation.DEPENDENCY_MODEL,
        reason=degradation.REASON_RETRY_EXHAUSTED,
        agent_type=CUSTOMER_SERVICE_CONFIG.name,
        trace_id=get_trace_id(),
        detail=exc.message,
    )


def replay_graph_augmentation(question: str) -> GraphAugmentation:
    """回放模式的图谱增强：预置问题返回预写段落，其余按实体未命中处理。"""
    preset = replay_library.chat_preset(question)
    if preset is None or not preset.passages:
        return GraphAugmentation(
            degraded=True, degradation_reason=DEGRADED_NO_ENTITY
        )
    return GraphAugmentation(
        passages=[
            GraphPassage(
                content=passage.content,
                score=1.0,
                entity_type=cast(PassageEntityType, passage.entity_type),
                entity_value=passage.entity_value,
                tool=passage.tool,
            )
            for passage in preset.passages
        ],
        matched_entities=[dict(entity) for entity in preset.matched_entities],
    )


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict]
    # 登录客户的使用者标识。图谱增强用它把客户节点收成「只认本人」——客户侧提问
    # 不能因为问句里出现别人的姓名就把别人的持仓拉进上下文（客户可见视图只有本人的）。
    user_id: int
    intent: Intent
    chunks: list[ChunkResult]
    # 融合前的分臂证据集：{"vector": 最高余弦, "keyword": 最高 BM25, "graph": 有段落则 1.0}。
    # 兜底判定用它而不是融合后的综合分——权重的职责是把上下文排出先后，不该让
    # 「图谱是否参与」改变「有没有依据」的结论（见 route_after_retrieve）。
    # 三条量纲不能混用，因此是集合而不是一个数：CONTEXT「证据分」。
    retrieval_evidence: dict[str, float]
    tool_calls: list[dict]
    answer: str
    citations: list[Citation]
    # 真正送进（或本该送进）模型的完整提示词。只有会调用模型的节点会写它：
    # 兜底与转人工是固定的脚本，不产生提示词，所以留痕里这一项为空。
    prompt: list[dict]
    # 数据查询分支这一轮的查询材料（生成的查询、命中的视图、行数）。它同样不是
    # 提示词，但属于「这一轮到底发生了什么」，随调试级留痕落库。
    data_query: dict
    # 数据查询分支「有行」时的客户侧结果表（ADR-0028）。它与 data_query 的去向正好
    # 相反：材料只落 30 天留痕，结果表只送达客户。
    data_answer: DataAnswerResponse | None


@dataclass
class ChatTurnResult:
    answer: str
    citations: list[Citation]
    intent: str
    content_classification: str
    trace_id: str = ""
    # 本轮是否走过任一降级路径（模型兜底、向量超时转关键词、缓存不可用……）。
    # 由降级留痕反查得出，而不是在各处手工累加——那样迟早会漏掉一处。
    degraded: bool = False
    # 有行的数据查询才带结果表（ADR-0028），其余分支与出口都是 None。
    data_answer: DataAnswerResponse | None = None


def build_retrieval_evidence(
    chunks: list[ChunkResult], *, has_graph_passages: bool = False
) -> dict[str, float]:
    """把「有没有依据」拆成按臂计的证据集（CONTEXT「证据分」，ADR-0022 决定 4）。

    各臂的原始最高分由 `search_chunks` 在**两路还分着**的时候算好带出来
    （`RetrievedChunks.evidence`）：RRF 把 hybrid 块合成一条之后，「向量臂最高
    多少、关键词臂最高多少」就再也分不开了，而 BM25 的量纲冒充余弦会让向量臂
    凭空达标。调用方给的是普通 list（测试替身）时退到 `arm_evidence` 反推，那条路
    只对单臂构造的候选成立。图谱段落是查出来的确定事实，有就算 1.0。
    """
    evidence = carried_evidence(chunks)
    evidence["graph"] = 1.0 if has_graph_passages else 0.0
    return evidence


def has_retrieval_evidence(
    evidence: dict[str, float],
    *,
    vector_threshold: float,
    keyword_threshold: float,
) -> bool:
    """分臂判定：任一臂达标即认为有依据（Q9）。RRF 与重排不参与这里。

    「该不该作答」是合规结论，不能被一次增强环节（RRF 只排序、重排只排序）的
    抖动改写；因此这里读的是各臂的原始分与各自的阈值。
    """
    return (
        evidence.get("vector", 0.0) >= vector_threshold
        or evidence.get("keyword", 0.0) >= keyword_threshold
        or evidence.get("graph", 0.0) > 0
    )


def _build_graph(db: Session, settings: Settings, driver: Driver, graph_namespace: str):
    graph = StateGraph(AgentState)

    def classify_node(state: AgentState) -> dict:
        return {"intent": classify_intent(state["question"])}

    def retrieve_node(state: AgentState) -> dict:
        # 要的是**召回候选**（两臂各 hybrid_recall_top_k 条、RRF 融合后的那一批），
        # 不是最终送进模型的条数：重排与保底在后面决定取几条上下文。少要一批等于
        # 让重排没得选。
        candidates = search_chunks(
            db,
            settings,
            query=state["question"],
            top_k=settings.hybrid_recall_top_k,
            agent_type=CUSTOMER_SERVICE_CONFIG.name,
        )
        # 重排是增强，由调用方显式串起来而不是塞进 `search_chunks`——后者会形成
        # service → rerank → provider → service 的模块加载环。关闭 / fake / 回放时它
        # 恒等保序、超时失败时退回 RRF 序，都不改变「有没有依据」（那是分臂证据的职责）。
        chunks = rerank_chunks(
            state["question"],
            candidates,
            settings,
            db=db,
            top_k=CUSTOMER_SERVICE_CONFIG.retrieval_top_k,
            agent_type=CUSTOMER_SERVICE_CONFIG.name,
        )
        tool_call = {
            "tool": "knowledge_search",
            "input": {
                "query": state["question"],
                "top_k": settings.hybrid_recall_top_k,
            },
            "output": {
                "candidate_count": len(candidates),
                "hit_count": len(chunks),
                "top_score": chunks[0].score if chunks else None,
                # 原始臂分要能看到：排查与校准读的是 evidence_score 那套量纲，
                # 不是融合后的 score。
                "retrieval_evidence": build_retrieval_evidence(chunks),
            },
        }
        return {"chunks": chunks, "tool_calls": [*state.get("tool_calls", []), tool_call]}

    def graph_augment_node(state: AgentState) -> dict:
        if settings.demo_replay:
            # 回放模式（ADR-0008）不连 Neo4j：预置问题返回预写的图谱段落，
            # 其余问题按「实体未命中」处理——这与真实链路里问题不含实体时的
            # 结果一致，融合照常按加法进行，向量分不打折。
            augmentation = replay_graph_augmentation(state["question"])
        else:
            augmentation = augment_with_graph(
                driver,
                db,
                namespace=graph_namespace,
                question=state["question"],
                timeout_seconds=settings.graphrag_query_timeout_seconds,
                # 客服链路是客户侧：图谱只认登录客户本人，别人的姓名解析不出实体，
                # 也就不会把别人的持仓或行业敞口融合进上下文（客户可见视图只有本人的）。
                only_customer_id=state.get("user_id"),
            )
        if augmentation.degradation_reason in DEPENDENCY_DEGRADATION_REASONS:
            # 图谱是增强，超时/不可用不该中断回答；但这是一次降级，要能统计到。
            # 统计口径统一成「超时 / 不可达」两类，图谱自己的细分原因进 detail。
            degradation.record(
                db,
                dependency=degradation.DEPENDENCY_GRAPH,
                reason=(
                    degradation.REASON_TIMEOUT
                    if augmentation.degradation_reason == DEGRADED_TIMEOUT
                    else degradation.REASON_UNAVAILABLE
                ),
                agent_type=CUSTOMER_SERVICE_CONFIG.name,
                trace_id=get_trace_id(),
                detail=augmentation.degradation_reason,
            )
        fused = fuse_and_rank(
            state["chunks"],
            augmentation.passages,
            vector_weight=settings.graphrag_vector_weight,
            graph_weight=settings.graphrag_graph_weight,
        )
        # 证据集在融合前取：融合会把相似度分乘上 vector_weight（默认 0.6），拿缩放
        # 后的综合分去比阈值，会让一条真实命中的结果被打成不合格——「图谱是增强不是
        # 依赖」这条约束也要求它不能。分臂判定见 route_after_retrieve。
        evidence = build_retrieval_evidence(
            state["chunks"], has_graph_passages=bool(augmentation.passages)
        )
        tool_call = {
            "tool": "graphrag_fusion",
            "input": {"question": state["question"]},
            "output": {
                "matched_entities": augmentation.matched_entities,
                "graph_hit_count": len(augmentation.passages),
                "degraded": augmentation.degraded,
                "degradation_reason": augmentation.degradation_reason,
                "retrieval_evidence": evidence,
            },
        }
        return {
            "chunks": fused,
            "retrieval_evidence": evidence,
            "tool_calls": [*state.get("tool_calls", []), tool_call],
        }

    def generate_node(state: AgentState) -> dict:
        chunks = state["chunks"]
        try:
            result = generate_grounded_answer(
                state["question"], state["history"], chunks, settings
            )
        except AppError as exc:
            # 退避重试与备用配置都在 provider 里走完了，到这里说明模型整体不可用。
            # 返回预设兜底回答而不是把错误抛给使用者，并留一条降级痕迹。
            report_model_failure(db, exc)
            return {"answer": model_failure_answer(settings), "citations": []}
        # 引用按正文 [N] 角标对齐：正文里悬空的角标（越界/模型没对应引用块）会被
        # 剔除，正文没写角标时退回模型自报的 citations 列表——见 citations.reconcile_answer。
        answer, citations = reconcile_answer(
            chunks, result.cited_chunk_numbers, result.text
        )
        # 提示词在这里按同一纯函数再拼一次，而不是从模型结果里取：留痕不该依赖
        # provider 有没有回传提示词，换掉 provider（或测试里打了桩）也不该丢这条。
        prompt = build_grounded_messages(state["question"], state["history"], chunks)
        return {"answer": answer, "citations": citations, "prompt": prompt}

    def fallback_node(state: AgentState) -> dict:
        return {"answer": fallback_message(settings), "citations": []}

    def chitchat_node(state: AgentState) -> dict:
        try:
            answer = generate_chitchat_reply(state["question"], settings)
        except AppError as exc:
            report_model_failure(db, exc)
            return {"answer": model_failure_answer(settings), "citations": []}
        return {
            "answer": answer,
            "citations": [],
            "prompt": build_chitchat_messages(state["question"]),
        }

    def handoff_node(state: AgentState) -> dict:
        return {"answer": handoff_message(settings), "citations": []}

    def data_query_node(state: AgentState) -> dict:
        # 数据查询是一类分支而不是一个工具（ADR-0025）：路由由 classify 定死，
        # 模型不参与「要不要查数据」这个决定。
        turn = answer_customer_data_question(
            db,
            settings,
            customer_id=state["user_id"],
            question=state["question"],
            history=state.get("history", []),
        )
        return {
            "answer": turn.answer,
            "citations": [],
            "data_query": turn.material,
            "data_answer": turn.data_answer,
        }

    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("graph_augment", graph_augment_node)
    graph.add_node("generate", generate_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("chitchat", chitchat_node)
    graph.add_node("handoff", handoff_node)
    graph.add_node("data_query", data_query_node)

    graph.set_entry_point("classify")

    def route_after_classify(state: AgentState) -> str:
        intent = state["intent"]
        if intent == Intent.CHITCHAT:
            return "chitchat"
        if intent == Intent.HANDOFF:
            return "handoff"
        # 非检索类意图不碰知识库：数据查询走复用的分析链路，没有引用可谈。
        if intent == Intent.DATA_QUERY:
            return "data_query"
        assert intent in RETRIEVAL_INTENTS
        return "retrieve"

    graph.add_conditional_edges("classify", route_after_classify)

    graph.add_edge("retrieve", "graph_augment")

    def route_after_retrieve(state: AgentState) -> str:
        # 分臂判定（Q9）：向量臂最高余弦、关键词臂最高 BM25、图谱段落三者任一达标
        # 即认为有依据。比的是融合前的臂内原始分（graph_augment_node 写进
        # retrieval_evidence），不是 chunks[0].score——后者是加权综合分，图谱一参与
        # 相似度分就被乘上 vector_weight，拿它判兜底会凭空抬高门槛。
        if not state["chunks"] or not has_retrieval_evidence(
            state.get("retrieval_evidence", {}),
            vector_threshold=settings.retrieval_score_threshold,
            keyword_threshold=settings.retrieval_keyword_score_threshold,
        ):
            return "fallback"
        return "generate"

    graph.add_conditional_edges("graph_augment", route_after_retrieve)

    graph.add_edge("generate", END)
    graph.add_edge("fallback", END)
    graph.add_edge("chitchat", END)
    graph.add_edge("handoff", END)
    graph.add_edge("data_query", END)

    return graph.compile()


def _serialize_snippets(chunks: list[ChunkResult]) -> list[dict]:
    return [
        {
            "knowledge_id": chunk.knowledge_id,
            "chunk_index": chunk.chunk_index,
            "heading_path": chunk.heading_path,
            "content": chunk.content,
            "score": chunk.score,
            "source": chunk.source,
            "title": chunk.title,
            "source_file": chunk.source_file,
        }
        for chunk in chunks
    ]


def _publish_risk_intent(
    db: Session,
    publisher: EventPublisher,
    *,
    customer_id: int,
    session_id: str,
    question: str,
    history: list[dict],
    now: datetime,
) -> None:
    """察觉高风险意图就广播一条事件。

    广播失败只记日志（`publish_safely` 的用意）：回答已经生成，不会因为风控那边
    没收到而变成一次错误——协作是增强。载荷只带判定结论，不带问题原文。

    事件时刻由调用方传入（ADR-0011），不在内部读时钟：这条时刻会落成关注记录的
    `occurred_at`，进而决定投顾端风险标记的时间窗，它得能被测试固定住。
    """
    signal = detect_risk_intent(question, history=history)
    if signal is None:
        return
    delivered = publish_safely(
        publisher,
        Event(
            event_type=EVENT_RISK_INTENT_DETECTED,
            source=SOURCE_CUSTOMER_SERVICE,
            payload={
                "customer_id": customer_id,
                "session_id": session_id,
                "intent_code": signal.code,
                "reason": signal.reason,
            },
            occurred_at=now,
            trace_id=get_trace_id(),
        ),
    )
    if not delivered:
        # 广播失败不影响这次回答，但要让「有多少次协作其实没发出去」可统计。
        degradation.record(
            db,
            dependency=degradation.DEPENDENCY_EVENT_BUS,
            reason=degradation.REASON_UNAVAILABLE,
            agent_type=CUSTOMER_SERVICE_CONFIG.name,
            trace_id=get_trace_id(),
        )


def run_customer_service_turn(
    db: Session,
    cache: redis.Redis,
    settings: Settings,
    *,
    driver: Driver,
    publisher: EventPublisher,
    session_id: str,
    user_id: int,
    question: str,
    now: datetime,
) -> ChatTurnResult:
    history_read = memory.read_history(cache, session_id)
    if history_read.degraded:
        # 缓存不可用不代表这一轮不能答：无上下文的单轮回答仍是可用结果。
        degradation.record(
            db,
            dependency=degradation.DEPENDENCY_CACHE,
            reason=degradation.REASON_UNAVAILABLE,
            agent_type=CUSTOMER_SERVICE_CONFIG.name,
            trace_id=get_trace_id(),
        )
    history = history_read.history

    graph = _build_graph(db, settings, driver, settings.neo4j_graph_namespace)
    start_token_usage()
    started = time.monotonic()
    final_state: AgentState = graph.invoke(
        {
            "question": question,
            "history": history,
            "tool_calls": [],
            "user_id": user_id,
        }
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    token_usage = get_token_usage()

    answer = final_state["answer"]
    citations = final_state.get("citations", [])
    tool_calls = final_state.get("tool_calls", [])
    content_classification = CUSTOMER_SERVICE_CONFIG.content_classification_default

    wrote_user = memory.append_turn(
        cache, session_id, role="user", content=question, settings=settings
    )
    wrote_assistant = memory.append_turn(
        cache, session_id, role="assistant", content=answer, settings=settings
    )
    if not (wrote_user and wrote_assistant):
        # 只在尚未因读取失败记过时补记；两条都失败也只留一条，避免一轮刷两行。
        if not history_read.degraded:
            degradation.record(
                db,
                dependency=degradation.DEPENDENCY_CACHE,
                reason=degradation.REASON_UNAVAILABLE,
                agent_type=CUSTOMER_SERVICE_CONFIG.name,
                trace_id=get_trace_id(),
            )

    archive.record_turn(
        db,
        session_id=session_id,
        user_id=user_id,
        agent_type=CUSTOMER_SERVICE_CONFIG.name,
        question=question,
        answer=answer,
        citations=citations,
        tool_calls=tool_calls,
        content_classification=content_classification,
    )

    # 调试级留痕与审计级留痕同回合各写各的：审计级永久保存，这一条到期会被清理。
    debug_trace.record(
        db,
        trace_id=get_trace_id(),
        agent_type=CUSTOMER_SERVICE_CONFIG.name,
        session_id=session_id,
        user_id=user_id,
        prompt=final_state.get("prompt"),
        retrieval_snippets=_serialize_snippets(final_state.get("chunks", [])),
        data_query=final_state.get("data_query"),
        prompt_tokens=token_usage.prompt_tokens if token_usage else None,
        completion_tokens=token_usage.completion_tokens if token_usage else None,
        duration_ms=duration_ms,
    )

    # 留痕之后再广播：本次对话对使用者的价值已经确定，订阅方收不收到都不改变它。
    _publish_risk_intent(
        db,
        publisher,
        customer_id=user_id,
        session_id=session_id,
        question=question,
        history=history,
        now=now,
    )

    trace_id = get_trace_id()
    return ChatTurnResult(
        answer=answer,
        citations=citations,
        intent=final_state["intent"].value,
        content_classification=content_classification,
        trace_id=trace_id,
        degraded=degradation.happened(db, trace_id=trace_id),
        data_answer=final_state.get("data_answer"),
    )
