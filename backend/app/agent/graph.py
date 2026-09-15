from dataclasses import dataclass
from typing import TypedDict

import redis
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agent import archive, memory
from app.agent.citations import Citation, build_citations
from app.agent.config import CUSTOMER_SERVICE_CONFIG
from app.agent.intent import RETRIEVAL_INTENTS, Intent, classify_intent
from app.knowledge.service import ChunkResult, search_chunks
from app.llm.provider import generate_chitchat_reply, generate_grounded_answer
from app.settings import Settings


def fallback_message(settings: Settings) -> str:
    return (
        "很抱歉，我在知识库里没有找到能支撑这个问题的依据，不想给您一个没有出处的答案。"
        f"建议您拨打人工客服热线 {settings.human_service_channel} 由人工为您核实。"
    )


def handoff_message(settings: Settings) -> str:
    return f"已为您转接人工客服，请拨打 {settings.human_service_channel}，会有专属客服为您处理。"


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict]
    intent: Intent
    chunks: list[ChunkResult]
    tool_calls: list[dict]
    answer: str
    citations: list[Citation]


@dataclass
class ChatTurnResult:
    answer: str
    citations: list[Citation]
    intent: str
    content_classification: str


def _build_graph(db: Session, settings: Settings):
    graph = StateGraph(AgentState)

    def classify_node(state: AgentState) -> dict:
        return {"intent": classify_intent(state["question"])}

    def retrieve_node(state: AgentState) -> dict:
        chunks = search_chunks(
            db, settings, query=state["question"], top_k=CUSTOMER_SERVICE_CONFIG.retrieval_top_k
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

    def generate_node(state: AgentState) -> dict:
        chunks = state["chunks"]
        result = generate_grounded_answer(state["question"], state["history"], chunks, settings)
        citations = build_citations(chunks, result.cited_chunk_numbers)
        return {"answer": result.text, "citations": citations}

    def fallback_node(state: AgentState) -> dict:
        return {"answer": fallback_message(settings), "citations": []}

    def chitchat_node(state: AgentState) -> dict:
        return {"answer": generate_chitchat_reply(state["question"], settings), "citations": []}

    def handoff_node(state: AgentState) -> dict:
        return {"answer": handoff_message(settings), "citations": []}

    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
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

    def route_after_retrieve(state: AgentState) -> str:
        chunks = state["chunks"]
        # search_chunks 依赖 Milvus 按相似度降序返回命中，chunks[0] 即最高分。
        if not chunks or chunks[0].score < settings.retrieval_score_threshold:
            return "fallback"
        return "generate"

    graph.add_conditional_edges("retrieve", route_after_retrieve)

    graph.add_edge("generate", END)
    graph.add_edge("fallback", END)
    graph.add_edge("chitchat", END)
    graph.add_edge("handoff", END)

    return graph.compile()


def run_customer_service_turn(
    db: Session,
    cache: redis.Redis,
    settings: Settings,
    *,
    session_id: str,
    user_id: int,
    question: str,
) -> ChatTurnResult:
    history = memory.get_history(cache, session_id)
    graph = _build_graph(db, settings)
    final_state: AgentState = graph.invoke(
        {"question": question, "history": history, "tool_calls": []}
    )

    answer = final_state["answer"]
    citations = final_state.get("citations", [])
    tool_calls = final_state.get("tool_calls", [])
    content_classification = CUSTOMER_SERVICE_CONFIG.content_classification_default

    memory.append_turn(cache, session_id, role="user", content=question, settings=settings)
    memory.append_turn(cache, session_id, role="assistant", content=answer, settings=settings)

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

    return ChatTurnResult(
        answer=answer,
        citations=citations,
        intent=final_state["intent"].value,
        content_classification=content_classification,
    )
