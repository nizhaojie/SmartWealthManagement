<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { PanelCard } from "@wealth/shared";
import { ElMessage, ElMessageBox, type UploadFile } from "element-plus";
import { errorMessage, formatDateTime } from "../format";
import { deleteDocument, listDocuments, uploadDocument } from "./api";
import {
  DOCUMENT_STATUSES,
  KNOWLEDGE_TYPES,
  STAGE_LABELS,
  STATUS_LABELS,
  type DocumentStatus,
  type IngestStage,
  type KnowledgeDocument,
  type KnowledgeType,
} from "./types";

/** 距过期不足 30 天算「即将过期」，与后端 expire_at 的语义一致。 */
const NEAR_EXPIRY_MS = 30 * 24 * 60 * 60 * 1000;
/** 有文档在 processing 时按这个间隔轮询，直到全部落定。 */
const POLL_INTERVAL_MS = 1500;

const documents = ref<KnowledgeDocument[]>([]);
const loading = ref(true);
const loadError = ref("");

const typeFilter = ref<KnowledgeType | "">("");
const statusFilter = ref<DocumentStatus | "">("");

const uploadType = ref<KnowledgeType>("FAQ");
const uploadTitle = ref("");
const selectedFile = ref<File | null>(null);
const uploading = ref(false);
const uploadError = ref("");

let pollTimer: number | null = null;

function statusTagType(status: DocumentStatus): "warning" | "success" | "danger" | "info" {
  if (status === "active") return "success";
  if (status === "failed") return "danger";
  if (status === "processing") return "warning";
  return "info";
}

function isNearExpiry(document: KnowledgeDocument): boolean {
  if (!document.expire_at) return false;
  return new Date(document.expire_at).getTime() - Date.now() <= NEAR_EXPIRY_MS;
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function loadDocuments(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    documents.value = await listDocuments({
      knowledgeType: typeFilter.value || undefined,
      status: statusFilter.value || undefined,
    });
    // 只有真的还有处理中的文档才轮询，避免停在一个空转的定时器上。
    stopPolling();
    if (documents.value.some((document) => document.status === "processing")) {
      pollTimer = window.setInterval(() => void loadDocuments(), POLL_INTERVAL_MS);
    }
  } catch (error) {
    loadError.value = errorMessage(error, "文档列表加载失败");
  } finally {
    loading.value = false;
  }
}

watch([typeFilter, statusFilter], loadDocuments, { immediate: true });
onUnmounted(stopPolling);

function handleFileChange(uploadFile: UploadFile): void {
  selectedFile.value = uploadFile.raw ?? null;
}

async function submitUpload(): Promise<void> {
  uploadError.value = "";
  if (!selectedFile.value) {
    uploadError.value = "请先选择一个文件";
    return;
  }
  uploading.value = true;
  try {
    await uploadDocument(selectedFile.value, uploadType.value, uploadTitle.value || undefined);
    ElMessage.success("已提交，正在处理中");
    selectedFile.value = null;
    uploadTitle.value = "";
    await loadDocuments();
  } catch (error) {
    uploadError.value = errorMessage(error, "上传失败");
  } finally {
    uploading.value = false;
  }
}

async function removeDocument(document: KnowledgeDocument): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除「${document.title}」？`, "删除文档", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    });
  } catch {
    // 取消确认不是错误：什么都不做。
    return;
  }
  try {
    await deleteDocument(document.knowledge_id);
    ElMessage.success("已删除");
    await loadDocuments();
  } catch (error) {
    loadError.value = errorMessage(error, "删除失败");
  }
}

const processingCount = computed(
  () => documents.value.filter((document) => document.status === "processing").length,
);
</script>

<template>
  <div class="documents">
    <PanelCard title="上传文档">
      <form class="upload" @submit.prevent="submitUpload">
        <label class="upload__field">
          <span class="upload__label">知识类型</span>
          <el-select v-model="uploadType" name="knowledge_type">
            <el-option v-for="type in KNOWLEDGE_TYPES" :key="type" :label="type" :value="type" />
          </el-select>
        </label>

        <label class="upload__field">
          <span class="upload__label">标题（可选）</span>
          <el-input v-model="uploadTitle" name="knowledge-title" placeholder="缺省取文件名" />
        </label>

        <el-upload
          class="upload__picker"
          :auto-upload="false"
          :limit="1"
          :on-change="handleFileChange"
          accept=".txt,.md,.docx"
        >
          <el-button name="pick-file">选择文件</el-button>
        </el-upload>

        <el-button
          type="primary"
          native-type="submit"
          name="upload-document"
          :loading="uploading"
          data-testid="upload-document"
        >
          上传
        </el-button>
      </form>
      <p v-if="uploadError" class="documents__error" role="alert" data-testid="upload-error">
        {{ uploadError }}
      </p>
    </PanelCard>

    <PanelCard title="文档列表">
      <form class="filters" @submit.prevent="loadDocuments">
        <label class="filters__field">
          <span class="filters__label">知识类型</span>
          <el-select v-model="typeFilter" name="filter-type" placeholder="全部">
            <el-option label="全部" value="" />
            <el-option v-for="type in KNOWLEDGE_TYPES" :key="type" :label="type" :value="type" />
          </el-select>
        </label>
        <label class="filters__field">
          <span class="filters__label">状态</span>
          <el-select v-model="statusFilter" name="filter-status" placeholder="全部">
            <el-option label="全部" value="" />
            <el-option
              v-for="status in DOCUMENT_STATUSES"
              :key="status"
              :label="STATUS_LABELS[status]"
              :value="status"
            />
          </el-select>
        </label>
        <el-button name="apply-document-filters" native-type="submit" :loading="loading">
          筛选
        </el-button>
      </form>

      <p v-if="loadError" class="documents__error" role="alert" data-testid="document-error">
        {{ loadError }}
      </p>
      <p v-else-if="!loading && documents.length === 0" class="documents__empty">
        还没有文档。先上传一份 FAQ 或产品资料。
      </p>
      <p v-if="processingCount" class="documents__polling" data-testid="document-polling">
        {{ processingCount }} 份文档处理中，列表会自动刷新。
      </p>

      <el-table v-if="documents.length" :data="documents" data-testid="documents-table">
        <el-table-column label="知识类型" prop="knowledge_type" width="100" />
        <el-table-column label="标题" prop="title" min-width="180" />
        <el-table-column label="来源文件" prop="source_file" min-width="160" />
        <el-table-column label="版本" prop="version" width="90" />
        <el-table-column label="状态" width="140">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">
              {{ STATUS_LABELS[row.status as DocumentStatus] }}
              <template v-if="row.status === 'processing' && row.stage">
                · {{ STAGE_LABELS[row.stage as IngestStage] }}
              </template>
            </el-tag>
            <el-tooltip v-if="row.status === 'failed' && row.failure_reason" :content="row.failure_reason">
              <span class="documents__reason">查看原因</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="入库时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="分块数" prop="chunk_count" width="90" />
        <el-table-column label="过期时间" width="200">
          <template #default="{ row }">
            <span v-if="row.expire_at">{{ formatDateTime(row.expire_at) }}</span>
            <span v-else>—</span>
            <el-tag v-if="isNearExpiry(row)" type="warning" size="small" class="documents__expiry">
              即将过期
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" name="delete-document" @click="removeDocument(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </PanelCard>
  </div>
</template>

<style scoped>
.documents {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.upload {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
}

.upload__field,
.filters__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.upload__label,
.filters__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
  margin-bottom: var(--wm-space-4);
}

.documents__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.documents__empty,
.documents__polling {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}

.documents__polling {
  margin-bottom: var(--wm-space-3);
}

.documents__reason {
  margin-left: var(--wm-space-2);
  color: var(--wm-color-danger);
  font-size: 0.8rem;
  cursor: help;
}

.documents__expiry {
  margin-left: var(--wm-space-2);
}
</style>
