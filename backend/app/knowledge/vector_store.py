import json
from functools import lru_cache
from typing import Any, TypedDict

from pymilvus import DataType, MilvusClient

from app.settings import Settings

VECTOR_FIELD = "vector"
OUTPUT_FIELDS = ["knowledge_id", "knowledge_type", "chunk_index", "heading_path", "content"]


class ChunkRecord(TypedDict):
    knowledge_id: int
    knowledge_type: str
    chunk_index: int
    heading_path: list[str]
    content: str
    vector: list[float]


class ChunkHit(TypedDict):
    knowledge_id: int
    knowledge_type: str
    chunk_index: int
    heading_path: list[str]
    content: str
    score: float


@lru_cache
def _client(uri: str) -> MilvusClient:
    return MilvusClient(uri=uri)


def get_client(settings: Settings) -> MilvusClient:
    return _client(settings.milvus_uri)


def ensure_collection(client: MilvusClient, collection_name: str, dimension: int) -> None:
    if not client.has_collection(collection_name):
        client.create_collection(
            collection_name=collection_name,
            dimension=dimension,
            primary_field_name="id",
            id_type="int",
            vector_field_name=VECTOR_FIELD,
            metric_type="COSINE",
            auto_id=True,
            consistency_level="Strong",
        )
        return

    description = client.describe_collection(collection_name)
    existing_dimension = next(
        field["params"]["dim"]
        for field in description["fields"]
        if field["name"] == VECTOR_FIELD and field["type"] == DataType.FLOAT_VECTOR
    )
    if existing_dimension != dimension:
        raise RuntimeError(
            f"Milvus collection '{collection_name}' 的向量维度为 {existing_dimension}，"
            f"与配置的 EMBEDDING_DIMENSION={dimension} 不一致，请先确认配置或删除重建集合"
        )


def insert_chunks(client: MilvusClient, collection_name: str, chunks: list[ChunkRecord]) -> None:
    if not chunks:
        return
    data = [
        {
            "vector": chunk["vector"],
            "knowledge_id": chunk["knowledge_id"],
            "knowledge_type": chunk["knowledge_type"],
            "chunk_index": chunk["chunk_index"],
            "heading_path": json.dumps(chunk["heading_path"], ensure_ascii=False),
            "content": chunk["content"],
        }
        for chunk in chunks
    ]
    client.insert(collection_name, data=data)


def delete_by_knowledge_id(client: MilvusClient, collection_name: str, knowledge_id: int) -> None:
    if not client.has_collection(collection_name):
        return
    client.delete(collection_name, filter=f"knowledge_id == {knowledge_id}")


def search(
    client: MilvusClient,
    collection_name: str,
    *,
    query_vector: list[float],
    top_k: int,
    knowledge_type: str | None = None,
) -> list[ChunkHit]:
    if not client.has_collection(collection_name):
        return []

    filter_expr = ""
    if knowledge_type:
        if "'" in knowledge_type:
            raise ValueError("knowledge_type 不允许包含单引号")
        filter_expr = f"knowledge_type == '{knowledge_type}'"
    raw_hits: list[list[dict[str, Any]]] = client.search(
        collection_name,
        data=[query_vector],
        filter=filter_expr,
        limit=top_k,
        output_fields=OUTPUT_FIELDS,
        consistency_level="Strong",
    )
    hits: list[ChunkHit] = []
    for hit in raw_hits[0]:
        entity = hit["entity"]
        hits.append(
            ChunkHit(
                knowledge_id=entity["knowledge_id"],
                knowledge_type=entity["knowledge_type"],
                chunk_index=entity["chunk_index"],
                heading_path=json.loads(entity["heading_path"]),
                content=entity["content"],
                score=hit["distance"],
            )
        )
    return hits
