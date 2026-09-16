from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
        extra="ignore",
    )

    database_url: str = "mysql+pymysql://wealth_app:wealth_app_pw@127.0.0.1:3307/wealth"
    test_database_url: str = "mysql+pymysql://wealth_app:wealth_app_pw@127.0.0.1:3307/wealth_test"

    # root 连接仅用于创建受限执行账号（迁移账号没有 CREATE USER / GRANT 权限）。
    mysql_root_url: str = "mysql+pymysql://root:root_pw@127.0.0.1:3307"
    # 数据分析 Agent 的受限执行账号：只对语义视图有 SELECT 权限（ADR-0010）。
    analytics_db_user: str = "wealth_analytics"
    analytics_db_password: str = "wealth_analytics_pw"
    # 结果行数上限：超出时截断并在响应中带截断标记。
    analytics_max_rows: int = 200
    # 查询超时上限（MySQL max_execution_time，毫秒）。
    analytics_query_timeout_ms: int = 5000
    # 「问题 → 查询」示例文件；空则使用随仓库提供的 query_examples.json。
    analytics_examples_path: str = ""

    redis_url: str = "redis://127.0.0.1:6380/0"
    test_redis_url: str = "redis://127.0.0.1:6380/1"

    milvus_uri: str = "http://127.0.0.1:19531"
    milvus_collection: str = "knowledge_chunks"
    test_milvus_collection: str = "knowledge_chunks_test"

    etcd_url: str = "http://127.0.0.1:12379"

    neo4j_uri: str = "bolt://127.0.0.1:7688"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "wealth_neo4j_pw"
    # Neo4j Community 版只有一个数据库，测试库与开发库靠这个属性分开（同一实例内隔离），
    # 而不是像 MySQL 那样连不同的库。
    neo4j_graph_namespace: str = "wealth"
    test_neo4j_graph_namespace: str = "wealth_test"

    minio_endpoint: str = "127.0.0.1:9001"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "wealth-knowledge"
    minio_secure: bool = False

    jwt_secret: str = "change-me-before-any-real-use"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    customer_token_audience: str = "customer-app"
    internal_token_audience: str = "internal-app"

    llm_provider: str = "fake"
    llm_model_name: str = ""
    llm_api_base: str = ""
    llm_api_key: str = ""

    embedding_provider: str = "fake"
    embedding_model_name: str = "text-embedding-v3"
    embedding_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: str = ""
    embedding_dimension: int = 1024

    demo_replay: bool = False

    retrieval_score_threshold: float = 0.35
    chat_memory_ttl_minutes: int = 30
    chat_memory_token_budget: int = 2000
    human_service_channel: str = "95588"

    @property
    def resolved_llm_provider(self) -> str:
        if not self.llm_api_key:
            return "fake"
        return self.llm_provider

    @property
    def resolved_embedding_provider(self) -> str:
        if not self.embedding_api_key:
            return "fake"
        return self.embedding_provider


@lru_cache
def get_settings() -> Settings:
    return Settings()
