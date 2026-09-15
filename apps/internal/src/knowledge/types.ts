export type KnowledgeType = "FAQ" | "产品" | "政策";
export type DocumentStatus = "processing" | "active" | "failed" | "expired";
export type IngestStage = "parse" | "chunk" | "embed" | "store";

export type ChunkHit = {
  knowledge_id: number;
  knowledge_type: KnowledgeType;
  chunk_index: number;
  heading_path: string[];
  content: string;
  score: number;
  title: string;
  source_file: string;
};

export type SearchResult = {
  hits: ChunkHit[];
  score_threshold: number;
};

export type KnowledgeDocument = {
  knowledge_id: number;
  knowledge_type: KnowledgeType;
  title: string;
  source_file: string;
  version: string;
  status: DocumentStatus;
  chunk_count: number;
  expire_at: string | null;
  create_time: string;
  stage: IngestStage | null;
  failure_reason: string | null;
};

export const KNOWLEDGE_TYPES: KnowledgeType[] = ["FAQ", "产品", "政策"];

export const DOCUMENT_STATUSES: DocumentStatus[] = ["processing", "active", "failed", "expired"];

export const STATUS_LABELS: Record<DocumentStatus, string> = {
  processing: "处理中",
  active: "已入库",
  failed: "处理失败",
  expired: "已过期",
};

export const STAGE_LABELS: Record<IngestStage, string> = {
  parse: "解析中",
  chunk: "分块中",
  embed: "生成向量中",
  store: "入库中",
};
