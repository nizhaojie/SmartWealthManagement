import json
import urllib.request
from dataclasses import dataclass, field

from app.exceptions import AppError
from app.knowledge.service import ChunkResult
from app.settings import Settings
from app.tracing import record_token_usage

LLM_SERVICE_FAILED_CODE = 1007
LLM_SERVICE_FAILED_MESSAGE = "对话模型调用失败"

CHITCHAT_SYSTEM_PROMPT = (
    "你是智能财富管家系统的智能客服，只回答产品要素、政策条款与常见问题，"
    "不做任何产品推荐或收益预测。当前问题与理财业务无关，请用一两句话礼貌回应，"
    "并引导客户提出产品、政策或常见问题方面的问题。"
)

GROUNDED_SYSTEM_PROMPT = (
    "你是智能财富管家系统的智能客服，只能依据下面提供的检索片段回答问题，"
    "不得使用片段之外的知识，不得做产品推荐或收益预测。"
    "每一句论断后面用形如[1]、[2]的编号标注其依据的片段序号，编号必须对应片段列表中的序号。"
    "严格以 JSON 格式输出：{\"answer\": \"带编号标注的回答\", \"citations\": [引用到的片段序号]}。"
)


@dataclass
class GroundedAnswer:
    text: str
    cited_chunk_numbers: list[int] = field(default_factory=list)


def build_grounded_messages(
    question: str, history: list[dict], chunks: list[ChunkResult]
) -> list[dict]:
    """组装送进模型的完整提示词：系统约束 + 会话历史 + 带编号的检索片段与问题。

    抽成公开的纯函数，好让调用方在写调试级留痕时取到与真正送进模型一致的那份提示词，
    而不是另拼一份近似的。
    """
    numbered_chunks = "\n".join(
        f"[{index}] {chunk.content}" for index, chunk in enumerate(chunks, start=1)
    )
    return [
        {"role": "system", "content": GROUNDED_SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": f"检索片段：\n{numbered_chunks}\n\n问题：{question}"},
    ]


def build_chitchat_messages(question: str) -> list[dict]:
    return [
        {"role": "system", "content": CHITCHAT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


def generate_grounded_answer(
    question: str,
    history: list[dict],
    chunks: list[ChunkResult],
    settings: Settings,
) -> GroundedAnswer:
    if settings.resolved_llm_provider == "fake":
        return _fake_grounded_answer(chunks)
    messages = build_grounded_messages(question, history, chunks)
    return _openai_compatible_grounded_answer(messages, settings)


def generate_chitchat_reply(question: str, settings: Settings) -> str:
    if settings.resolved_llm_provider == "fake":
        return _fake_chitchat_reply()
    return _openai_compatible_chitchat_reply(build_chitchat_messages(question), settings)


def _fake_grounded_answer(chunks: list[ChunkResult]) -> GroundedAnswer:
    top = chunks[:3]
    sentences = [f"{chunk.content}[{index}]" for index, chunk in enumerate(top, start=1)]
    text = "根据知识库资料：" + " ".join(sentences)
    return GroundedAnswer(text=text, cited_chunk_numbers=list(range(1, len(top) + 1)))


def _fake_chitchat_reply() -> str:
    return (
        "我是专注产品要素、政策条款与常见问题的智能客服，这个话题暂时帮不上忙，"
        "欢迎随时向我咨询理财产品、政策或常见问题～"
    )


def chat_completion(messages: list[dict], settings: Settings) -> str:
    """调用 OpenAI 兼容的 chat 接口；失败统一折算成业务错误码。"""
    body = json.dumps(
        {"model": settings.llm_model_name, "messages": messages, "temperature": 0.2}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.llm_api_base.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.llm_api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
        usage = payload.get("usage")
        if isinstance(usage, dict):
            # token 明细进调试级留痕（不落日志）；没开累计时这个调用是空操作。
            record_token_usage(
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        return payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise AppError(LLM_SERVICE_FAILED_CODE, LLM_SERVICE_FAILED_MESSAGE) from exc


def _openai_compatible_grounded_answer(
    messages: list[dict], settings: Settings
) -> GroundedAnswer:
    content = chat_completion(messages, settings)
    try:
        parsed = json.loads(content)
        return GroundedAnswer(
            text=str(parsed["answer"]),
            cited_chunk_numbers=[int(number) for number in parsed.get("citations", [])],
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return GroundedAnswer(text=content, cited_chunk_numbers=[])


def _openai_compatible_chitchat_reply(messages: list[dict], settings: Settings) -> str:
    return chat_completion(messages, settings)
