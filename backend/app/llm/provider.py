import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field

from app.exceptions import AppError
from app.knowledge.service import ChunkResult
from app.replay import library as replay_library
from app.settings import Settings
from app.tracing import record_token_usage

logger = logging.getLogger("app.llm")

LLM_SERVICE_FAILED_CODE = 1007
LLM_SERVICE_FAILED_MESSAGE = "对话模型调用失败"

# 预设兜底回答：退避重试与备用配置都失败之后返回它，而不是把错误抛给使用者。
# 它是脚本，不经过模型——走到这一步的前提正是模型不可用。
MODEL_FAILURE_TEMPLATE = (
    "抱歉，智能回答服务暂时不可用，请稍后重试。"
    "如需帮助可拨打人工客服热线 {channel}，由人工为您核实。"
)

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
    # 回放模式（ADR-0008）不发起任何模型调用：预置问题返回预写回答，其余问题
    # 用与 fake provider 相同的确定性拼装——引用序号来自真实检索结果，角标合法。
    if settings.demo_replay:
        preset = replay_library.chat_preset(question)
        if preset is not None:
            return GroundedAnswer(text=preset.answer, cited_chunk_numbers=list(preset.cited))
        return _fake_grounded_answer(chunks)
    if settings.resolved_llm_provider == "fake":
        return _fake_grounded_answer(chunks)
    messages = build_grounded_messages(question, history, chunks)
    return _openai_compatible_grounded_answer(messages, settings)


def generate_chitchat_reply(question: str, settings: Settings) -> str:
    if settings.demo_replay:
        return replay_library.CHITCHAT_PRESETS.get(
            question.strip(), _fake_chitchat_reply()
        )
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


@dataclass(frozen=True)
class LlmEndpoint:
    """模型调用的一份配置。主配置与备用配置结构相同，只是取值来源不同。"""

    label: str
    api_base: str
    api_key: str
    model_name: str

    @property
    def usable(self) -> bool:
        return bool(self.api_base and self.api_key)


def model_failure_answer(settings: Settings) -> str:
    """模型不可用时的预设兜底回答（需求文档 F5.3 的最后一步）。"""
    return MODEL_FAILURE_TEMPLATE.format(channel=settings.human_service_channel)


def _endpoints(settings: Settings, *, allow_backup: bool = True) -> list[LlmEndpoint]:
    """按顺序尝试的模型配置：主配置在前，备用配置在后。

    备用配置未填 ``llm_backup_api_key`` 时整条跳过——否则会拿着空 key 去请求一次，
    白白多等一个超时。主配置的可用性由 ``resolved_llm_provider`` 在外面保证：
    fake provider 根本不会走到这里。

    ``allow_backup=False`` 时只剩主配置：检索链上的重排用它（见 ``chat_completion``）。
    """
    endpoints = [
        LlmEndpoint(
            label="primary",
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
        )
    ]
    backup = LlmEndpoint(
        label="backup",
        api_base=settings.llm_backup_api_base,
        api_key=settings.llm_backup_api_key,
        model_name=settings.llm_backup_model_name,
    )
    if allow_backup and backup.usable:
        endpoints.append(backup)
    return [endpoint for endpoint in endpoints if endpoint.usable]


def _request_chat(endpoint: LlmEndpoint, messages: list[dict], *, timeout: float) -> str:
    """一次模型调用。抛原始异常，退避与换配置由 `chat_completion` 决定。"""
    body = json.dumps(
        {"model": endpoint.model_name, "messages": messages, "temperature": 0.2}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint.api_base.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {endpoint.api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    usage = payload.get("usage")
    if isinstance(usage, dict):
        # token 明细进调试级留痕（不落日志）；没开累计时这个调用是空操作。
        record_token_usage(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
    return payload["choices"][0]["message"]["content"]


def chat_completion(
    messages: list[dict],
    settings: Settings,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    allow_backup: bool = True,
) -> str:
    """调用 OpenAI 兼容的 chat 接口，带退避重试与备用配置。

    失败链路（需求文档 F5.3）：同一配置内按指数退避重试 ``llm_max_retries`` 次
    （间隔 1s / 2s / 4s …，可配），仍失败则换备用配置再走一遍同样的重试，全部失败
    才折算成业务错误码。退避等待可配，测试里置 0 即可不必真的等待。

    三个可选参数是给**检索链上的重排**（`app.knowledge.rerank`）用的，默认值保持主
    链路的既有行为不变：重排走单次调用、`rerank_timeout_seconds` 超时、不用备用配置。
    主链路那套「30s × (1+3 次重试) 再切备用」是为「回答必须尽量产出」设计的，搬到
    检索链上会把 2s 的检索变成 30s+。
    """
    endpoints = _endpoints(settings, allow_backup=allow_backup)
    retries = max(
        settings.llm_max_retries if max_retries is None else max_retries, 0
    )
    request_timeout = settings.llm_timeout_seconds if timeout is None else timeout
    last_error: Exception | None = None

    for endpoint in endpoints:
        for attempt in range(retries + 1):
            try:
                return _request_chat(endpoint, messages, timeout=request_timeout)
            except Exception as exc:  # noqa: BLE001 - 换配置/退避前的统一收口
                last_error = exc
                logger.warning(
                    "模型调用失败 endpoint=%s attempt=%s/%s",
                    endpoint.label,
                    attempt + 1,
                    retries + 1,
                    exc_info=True,
                )
                if attempt < retries:
                    # 第 n 次重试前等 backoff * 2^(n-1)：1s / 2s / 4s …
                    time.sleep(settings.llm_retry_backoff_seconds * (2**attempt))

    raise AppError(LLM_SERVICE_FAILED_CODE, LLM_SERVICE_FAILED_MESSAGE) from last_error


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
