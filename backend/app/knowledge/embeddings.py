import hashlib
import json
import math
import urllib.request

from app.exceptions import AppError
from app.settings import Settings

EMBEDDING_SERVICE_FAILED_CODE = 1001
EMBEDDING_SERVICE_FAILED_MESSAGE = "Embedding 服务调用失败"

# 兼容服务单次请求允许的最大输入条数（DashScope text-embedding-v3 实测 10 条，
# 第 11 条起返回 400）。
EMBEDDING_MAX_BATCH_SIZE = 10


def embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    if settings.resolved_embedding_provider == "fake":
        return [_fake_embedding(text, settings.embedding_dimension) for text in texts]
    return _openai_compatible_embedding(texts, settings)


def _fake_embedding(text: str, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    normalized = text.strip().lower()
    bigrams = [normalized[i : i + 2] for i in range(len(normalized) - 1)]
    tokens = bigrams or [normalized or "_empty_"]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [v / norm for v in vector]


def _openai_compatible_embedding(texts: list[str], settings: Settings) -> list[list[float]]:
    # 兼容服务对单次请求的输入条数有上限（DashScope 为 10 条），一次全发会被整体
    # 拒绝；按上限分批，各批按原顺序拼接，对调用方保持一次调用的语义。
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_MAX_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_MAX_BATCH_SIZE]
        vectors.extend(_embedding_request(batch, settings))
    return vectors


def _embedding_request(texts: list[str], settings: Settings) -> list[list[float]]:
    body = json.dumps({"model": settings.embedding_model_name, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.embedding_api_base.rstrip('/')}/embeddings",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.embedding_api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
        return [item["embedding"] for item in payload["data"]]
    except Exception as exc:
        raise AppError(EMBEDDING_SERVICE_FAILED_CODE, EMBEDDING_SERVICE_FAILED_MESSAGE) from exc
