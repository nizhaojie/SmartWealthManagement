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
from app.agent.citations import Citation, build_citations
from app.agent.config import CUSTOMER_SERVICE_CONFIG
from app.agent.fusion import fuse_and_rank
from app.agent.intent import RETRIEVAL_INTENTS, Intent, classify_intent
from app.agent.risk_intent import detect_risk_intent
from app.event_bus import (
    EVENT_RISK_INTENT_DETECTED,
    SOURCE_CUSTOMER_SERVICE,
    Event,
    EventPublisher,
    publish_safely,
)
from app.exceptions import AppError
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
    intent: Intent
    chunks: list[ChunkResult]
    tool_calls: list[dict]
    answer: str
    citations: list[Citation]
    # 真正送进（或本该送进）模型的完整提示词。只有会调用模型的节点会写它：
    # 兜底与转人工是固定的脚本，不产生提示词，所以留痕里这一项为空。
    prompt: list[dict]


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


def _build_graph(db: Session, settings: Settings, driver: Driver, graph_namespace: str):
    graph = StateGraph(AgentState)

    def classify_node(state: AgentState) -> dict:
        return {"intent": classify_intent(state["question"])}

    def retrieve_node(state: AgentState) -> dict:
        chunks = search_chunks(
            db,
            settings,
            query=state["question"],
            top_k=CUSTOMER_SERVICE_CONFIG.retrieval_top_k,
            agent_type=CUSTOMER_SERVICE_CONFIG.name,
        )
        tool_call = {
            "tool": "knowledge_search",
            "input": {"query": state["question"], "top_k": CUSTOMER_SERVICE_CONFIG.retrieval_top_k},
            "output": {
                "hit_count": len(chunks),
                "top_score": chunks[0].score if chunks else None,
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
        tool_call = {
            "tool": "graphrag_fusion",
            "input": {"question": state["question"]},
            "output": {
                "matched_entities": augmentation.matched_entities,
                "graph_hit_count": len(augmentation.passages),
                "degraded": augmentation.degraded,
                "degradation_reason": augmentation.degradation_reason,
            },
        }
        return {"chunks": fused, "tool_calls": [*state.get("tool_calls", []), tool_call]}

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
        citations = build_citations(chunks, result.cited_chunk_numbers)
        # 提示词在这里按同一纯函数再拼一次，而不是从模型结果里取：留痕不该依赖
        # provider 有没有回传提示词，换掉 provider（或测试里打了桩）也不该丢这条。
        prompt = build_grounded_messages(state["question"], state["history"], chunks)
        return {"answer": result.text, "citations": citations, "prompt": prompt}

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

    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("graph_augment", graph_augment_node)
    graph.add_node("generate", generate_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("chitchat", chitchat_node)
    graph.add_node("handoff", handoff_node)

    graph.set_entry_point("classify")

    def route_after_classify(state: AgentState) -> str:
        intent = state["intent"]
        if intent == Intent.CHITCHAT:
            return "chitchat"
        if intent == Intent.HANDOFF:
            return "handoff"
        assert intent in RETRIEVAL_INTENTS
        return "retrieve"

    graph.add_conditional_edges("classify", route_after_classify)

    graph.add_edge("retrieve", "graph_augment")

    def route_after_retrieve(state: AgentState) -> str:
        chunks = state["chunks"]
        # 融合已经把向量结果与图谱结果按综合分排好序（graph_augment_node），
        # chunks[0] 即最高分，不论它来自哪条路径。
        if not chunks or chunks[0].score < settings.retrieval_score_threshold:
            return "fallback"
        return "generate"

    graph.add_conditional_edges("graph_augment", route_after_retrieve)

    graph.add_edge("generate", END)
    graph.add_edge("fallback", END)
    graph.add_edge("chitchat", END)
    graph.add_edge("handoff", END)

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
        {"question": question, "history": history, "tool_calls": []}
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
    )
