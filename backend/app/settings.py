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
    # 缓存读写的连接与读写超时。不设时一次连接挂起会把请求线程一直吊着，
    # 「缓存不可用就直连数据库」就无从触发。
    redis_connect_timeout_seconds: float = 2.0
    redis_socket_timeout_seconds: float = 2.0

    milvus_uri: str = "http://127.0.0.1:19531"
    milvus_collection: str = "knowledge_chunks"
    test_milvus_collection: str = "knowledge_chunks_test"

    etcd_url: str = "http://127.0.0.1:12379"

    neo4j_uri: str = "bolt://127.0.0.1:7688"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "wealth_neo4j_pw"
    # 建立连接的超时。查询本身的墙钟超时由 graphrag_query_timeout_seconds 控制，
    # 两者管的阶段不同：这个管「连不上要等多久」，那个管「连上了但算得慢」。
    neo4j_connection_timeout_seconds: float = 2.0
    # Neo4j Community 版只有一个数据库，测试库与开发库靠这个属性分开（同一实例内隔离），
    # 而不是像 MySQL 那样连不同的库。
    neo4j_graph_namespace: str = "wealth"
    test_neo4j_graph_namespace: str = "wealth_test"

    minio_endpoint: str = "127.0.0.1:9001"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "wealth-knowledge"
    minio_secure: bool = False

    # HS256 的密钥长度直接决定签名强度，PyJWT 对 <32 字节的密钥会发
    # InsecureKeyLengthWarning。缺省占位符刻意做到 ≥32 字节，生产环境仍须
    # 在 .env 里换成一份等长（或更长）的随机密钥。
    jwt_secret: str = "change-me-before-any-real-use-32bytes"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    customer_token_audience: str = "customer-app"
    internal_token_audience: str = "internal-app"

    llm_provider: str = "fake"
    llm_model_name: str = ""
    llm_api_base: str = ""
    llm_api_key: str = ""

    # 模型调用的降级链路（需求文档 F5.3）：单次调用超时 → 同一配置内指数退避重试
    # （间隔 = backoff * 1, 2, 4 …，即需求文档的 1s / 2s / 4s），最多重试
    # `llm_max_retries` 次（总调用次数 = 1 + 重试次数）→ 仍失败切备用配置走同样的
    # 重试 → 再失败返回预设兜底回答。三个阈值都可配置，改策略不改代码。
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3
    llm_retry_backoff_seconds: float = 1.0
    # 备用配置（OpenAI → 本地 Qwen）。未配置 api_key 时这条链路整体跳过。
    llm_backup_model_name: str = ""
    llm_backup_api_base: str = ""
    llm_backup_api_key: str = ""

    embedding_provider: str = "fake"
    embedding_model_name: str = "text-embedding-v3"
    embedding_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: str = ""
    embedding_dimension: int = 1024

    demo_replay: bool = False

    # 检索兜底阈值改为**分臂判定**（app.agent.graph 的 route_after_retrieve）：
    # 向量臂最高余弦、关键词臂最高 BM25、图谱段落三者任一达标即认为有依据。
    # 两个量纲不同，因此各有各的阈值——混用一个数会把一侧的结果整体打成兜底。
    #
    # 向量臂阈值：真实 embedding（如 text-embedding-v3）对无关文本的余弦也能到
    # 0.4~0.5，阈值必须校准在这条「无关噪声基线」之上。
    retrieval_score_threshold: float = 0.55
    # 关键词臂阈值：量纲是 **BM25 分**（不再是「命中字词占比」），且随语料规模漂移
    # （df / avgdl 在全语料上统计）。取值由 golden 集校准脚本产出；语料显著变化后
    # 要重跑校准。当前默认值只是占位，别照它调参。
    retrieval_keyword_score_threshold: float = 0.35
    # 每个召回臂各自返回的候选数（向量臂与关键词臂各出这么多条，再 RRF 融合）。
    hybrid_recall_top_k: int = 20
    # RRF 的平滑常数：rrf_score = Σ 1/(rrf_k + rank_arm)。它只用位次，天然跨量纲，
    # 免去「余弦与 BM25 怎么归一化」这件事。
    rrf_k: int = 60
    # 可选的 jieba 用户词典路径（一行一个词，不存在则跳过）。本 slice 不提供词表，
    # 这条只是「将来要加金融词表时不必改代码」的接缝。
    jieba_user_dict_path: str = ""
    chat_memory_ttl_minutes: int = 30
    chat_memory_token_budget: int = 2000
    human_service_channel: str = "95588"

    # 调试级留痕的保留期（天）。期满后清理任务删除它们，审计级留痕不受影响。
    # 清理的时间基准由调用方显式传入（ADR-0011），这个值只决定保留多久。
    debug_trace_retention_days: int = 30

    # 置信度的周期校准把时间衰减后低于该阈值的画像标签标记为已过期。
    profile_tag_expiry_threshold: float = 0.4
    # 周期校准的间隔（分钟），缺省每天一次；进程内调度，不引入分布式任务队列。
    calibration_interval_minutes: int = 24 * 60

    # 综合重排的场景权重覆盖：{场景: {因子: 权重}}。只给需要调整的场景写值，
    # 其余场景用 app.customer_profile.rerank 里的缺省表——调整策略不改代码。
    confidence_rerank_weights: dict[str, dict[str, float]] = {}

    # GraphRAG 融合排序权重：综合分 = vector_weight * 向量分 + graph_weight * 图谱分。
    # 两者默认相加为 1，与既有 retrieval_score_threshold 同一量纲，改权重不改代码。
    graphrag_vector_weight: float = 0.6
    graphrag_graph_weight: float = 0.4
    # 图谱查询墙钟超时（秒）；超时静默降级为纯向量检索。需求文档 F5.3 的口径是 3s。
    graphrag_query_timeout_seconds: float = 3.0
    # 关系图可视化入口的墙钟超时（秒）；超时返回空图而不是把异常抛给界面。
    graph_view_timeout_seconds: float = 3.0

    # 向量检索的墙钟超时（秒）；超时降级为针对分块镜像的 MySQL 关键词检索。
    # 需求文档 F5.3 的阈值口径就是 2s。
    vector_search_timeout_seconds: float = 2.0

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
