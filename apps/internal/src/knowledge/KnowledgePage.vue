<script setup lang="ts">
import { ElMessage, ElMessageBox, type UploadFile } from "element-plus";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { deleteDocument, listDocuments, uploadDocument } from "./api";
import {
  DOCUMENT_STATUSES,
  KNOWLEDGE_TYPES,
  STAGE_LABELS,
  STATUS_LABELS,
  type DocumentStatus,
  type KnowledgeDocument,
  type KnowledgeType,
} from "./types";

const NEAR_EXPIRY_MS = 30 * 24 * 60 * 60 * 1000;
const POLL_INTERVAL_MS = 1500;

const documents = ref<KnowledgeDocument[]>([]);
const loading = ref(false);
const loadError = ref("");

const typeFilter = ref<KnowledgeType | "">("");
const statusFilter = ref<DocumentStatus | "">("");

const uploadType = ref<KnowledgeType>("FAQ");
const selectedFile = ref<File | null>(null);
const uploading = ref(false);
const uploadError = ref("");

let pollTimer: ReturnType<typeof setInterval> | undefined;

const hasProcessingDocuments = computed(() =>
  documents.value.some((doc) => doc.status === "processing"),
);

function statusTagType(status: DocumentStatus): "info" | "success" | "danger" | "warning" {
  if (status === "active") return "success";
  if (status === "failed") return "danger";
  if (status === "processing") return "warning";
  return "info";
}

function isNearExpiry(doc: KnowledgeDocument): boolean {
  if (doc.status !== "active" || !doc.expire_at) {
    return false;
  }
  const remainingMs = new Date(doc.expire_at).getTime() - Date.now();
  return remainingMs > 0 && remainingMs <= NEAR_EXPIRY_MS;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

async function loadDocuments() {
  loading.value = true;
  loadError.value = "";
  try {
    documents.value = await listDocuments({
      knowledgeType: typeFilter.value || undefined,
      status: statusFilter.value || undefined,
    });
    if (hasProcessingDocuments.value) {
      schedulePolling();
    }
  } catch (error) {
    loadError.value = errorMessage(error, "加载文档列表失败");
  } finally {
    loading.value = false;
  }
}

function schedulePolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    if (!hasProcessingDocuments.value) {
      clearInterval(pollTimer);
      pollTimer = undefined;
      return;
    }
    try {
      documents.value = await listDocuments({
        knowledgeType: typeFilter.value || undefined,
        status: statusFilter.value || undefined,
      });
    } catch {
      // 轮询失败不打断页面，下一轮再试。
    }
  }, POLL_INTERVAL_MS);
}

function handleFileChange(file: UploadFile) {
  selectedFile.value = file.raw ?? null;
}

async function onUpload() {
  if (!selectedFile.value) {
    uploadError.value = "请先选择要上传的文件";
    return;
  }
  uploadError.value = "";
  uploading.value = true;
  try {
    await uploadDocument(selectedFile.value, uploadType.value);
    selectedFile.value = null;
    ElMessage.success("已提交，正在处理中");
    await loadDocuments();
  } catch (error) {
    uploadError.value = errorMessage(error, "上传失败");
  } finally {
    uploading.value = false;
  }
}

async function onDelete(doc: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm(`确认删除《${doc.title}》？删除后将无法被检索到。`, "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteDocument(doc.knowledge_id);
    ElMessage.success("已删除");
    await loadDocuments();
  } catch (error) {
    ElMessage.error(errorMessage(error, "删除失败"));
  }
}

watch([typeFilter, statusFilter], loadDocuments);

onMounted(loadDocuments);
onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer);
  }
});
</script>

<template>
  <div class="knowledge-page">
    <el-card class="knowledge-page__upload">
      <h3>上传文档</h3>
      <div class="knowledge-page__upload-form">
        <el-select v-model="uploadType" placeholder="知识类型" style="width: 140px">
          <el-option v-for="type in KNOWLEDGE_TYPES" :key="type" :label="type" :value="type" />
        </el-select>
        <el-upload
          :auto-upload="false"
          :limit="1"
          :on-change="handleFileChange"
          :show-file-list="true"
          accept=".txt,.md,.docx"
        >
          <el-button>选择文件</el-button>
        </el-upload>
        <el-button type="primary" :loading="uploading" @click="onUpload">上传</el-button>
      </div>
      <p v-if="uploadError" role="alert" class="knowledge-page__error">{{ uploadError }}</p>
    </el-card>

    <el-card class="knowledge-page__list">
      <div class="knowledge-page__filters">
        <el-select v-model="typeFilter" placeholder="按知识类型筛选" clearable style="width: 160px">
          <el-option v-for="type in KNOWLEDGE_TYPES" :key="type" :label="type" :value="type" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="按状态筛选" clearable style="width: 160px">
          <el-option v-for="status in DOCUMENT_STATUSES" :key="status" :label="STATUS_LABELS[status]" :value="status" />
        </el-select>
      </div>

      <p v-if="loadError" role="alert" class="knowledge-page__error">{{ loadError }}</p>

      <el-table :data="documents" v-loading="loading">
        <el-table-column prop="knowledge_type" label="知识类型" width="90" />
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="source_file" label="来源文件" />
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="状态" width="180">
          <template #default="{ row }: { row: KnowledgeDocument }">
            <el-tag :type="statusTagType(row.status)">
              {{ STATUS_LABELS[row.status] }}
              <template v-if="row.status === 'processing' && row.stage">
                · {{ STAGE_LABELS[row.stage] }}
              </template>
            </el-tag>
            <el-tooltip v-if="row.status === 'failed' && row.failure_reason" :content="row.failure_reason">
              <el-tag type="danger" size="small" style="margin-left: 4px">查看原因</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="入库时间" width="180">
          <template #default="{ row }: { row: KnowledgeDocument }">
            {{ formatDateTime(row.create_time) }}
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块数" width="80" />
        <el-table-column label="过期时间" width="200">
          <template #default="{ row }: { row: KnowledgeDocument }">
            {{ formatDateTime(row.expire_at) }}
            <el-tag v-if="isNearExpiry(row)" type="warning" size="small">即将过期</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }: { row: KnowledgeDocument }">
            <el-button type="danger" size="small" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.knowledge-page__upload-form {
  display: flex;
  align-items: center;
  gap: 12px;
}

.knowledge-page__filters {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.knowledge-page__error {
  color: var(--el-color-danger);
}
</style>
