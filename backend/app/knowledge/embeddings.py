import hashlib
import json
import math
import urllib.request

from app.exceptions import AppError
from app.settings import Settings

EMBEDDING_SERVICE_FAILED_CODE = 1001
EMBEDDING_SERVICE_FAILED_MESSAGE = "Embedding 服务调用失败"


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
