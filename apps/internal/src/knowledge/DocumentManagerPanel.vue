<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { PaginationBar, PanelCard, usePagination } from "@wealth/shared";
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
/** 这一页还有文档在 processing 时按这个间隔轮询，直到它们全部落定。 */
const POLL_INTERVAL_MS = 1500;

const typeFilter = ref<KnowledgeType | "">("");
const statusFilter = ref<DocumentStatus | "">("");

const uploadType = ref<KnowledgeType>("FAQ");
const uploadTitle = ref("");
const selectedFile = ref<File | null>(null);
const uploading = ref(false);
const uploadError = ref("");

// 删除失败的原因自己留一份，不复用列表的 `errorMessage`：`refresh()` 每次取数都会把那个
// 清空，于是「删除失败」会在随后那次成功重取的瞬间消失，看起来像什么都没发生。
const actionError = ref("");

const {
  items: documents,
  total,
  page,
  pageSize,
  loading,
  errorMessage: documentError,
  refresh,
  goTo,
  reset,
} = usePagination<KnowledgeDocument>(
  (query) =>
    listDocuments(
      {
        knowledgeType: typeFilter.value || undefined,
        status: statusFilter.value || undefined,
      },
      query,
    ),
  { failureMessage: "文档列表加载失败" },
);

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

/** 来源文件列只显示文件名，去掉「金融政策/」这类目录前缀——目录读不出更多东西，
 *  却占着一列的宽度，是把这张九列表格顶出容器的主要一块。 */
function fileName(sourceFile: string): string {
  const segments = sourceFile.split(/[/\\]/);
  return segments[segments.length - 1] || sourceFile;
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

/**
 * 取完一页之后重新决定要不要轮询：只有**这一页**真的还有处理中的文档才留着定时器。
 *
 * 分页之后没有「全量列表」可看，轮询因此按页判定：这一页落定了就停下，别的页上的
 * processing 由那一页自己的轮询负责——停在别人的页上只会空转，而且空转的每一次请求
 * 都在刷新一张屏幕上没有的表。
 */
function syncPolling(): void {
  stopPolling();
  if (documents.value.some((document) => document.status === "processing")) {
    pollTimer = window.setInterval(() => void pollCurrentPage(), POLL_INTERVAL_MS);
  }
}

/** 轮询刷的是**当前这一页**，不是第一页：定时器把人拽回第一页，正在看的第 3 页就自己跑了。 */
async function pollCurrentPage(): Promise<void> {
  // 上一拍还没回来就跳过这一拍：两个请求各写一次 `items`，后到的那个会把先到的覆盖掉。
  if (loading.value) {
    return;
  }
  await refresh();
  syncPolling();
}

/** 取第一页并在取完之后重新决定轮询：首次进入、改筛选、上传后回第一页都走这里。 */
async function loadFirstPage(): Promise<void> {
  await reset();
  syncPolling();
}

async function turnTo(next: number): Promise<void> {
  await goTo(next);
  // 换了一页就是换了一批文档：有没有 processing 要重新判一次。
  syncPolling();
}

watch([typeFilter, statusFilter], loadFirstPage);
onMounted(loadFirstPage);
onUnmounted(stopPolling);

const selectedFileName = computed(() => selectedFile.value?.name ?? "");

function handleFileChange(uploadFile: UploadFile): void {
  selectedFile.value = uploadFile.raw ?? null;
}

/** 已经选过文件后再选一份会走 exceed 分支：直接替换选中项，不必先清空。 */
function handleFileExceed(files: File[]): void {
  selectedFile.value = files[0] ?? null;
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
    // 刚上传的文档按入库时间倒序排在第一页最前，而且多半还是 processing：回第一页
    // 才看得到它，轮询也要跟着起来。
    await loadFirstPage();
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
  actionError.value = "";
  try {
    await deleteDocument(document.knowledge_id);
    ElMessage.success("已删除");
    // 重取当前这一页，不回到第一页：删掉的未必是这一页唯一一条。删空了也不会没有出路——
    // 分页条留着（越界页 `items` 为空但 `total` 不变），人可以自己往回翻。
    await refresh();
    syncPolling();
  } catch (error) {
    actionError.value = errorMessage(error, "删除失败");
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

        <div class="upload__field">
          <span class="upload__label">文件</span>
          <!-- show-file-list 关掉：EP 的文件列表渲染在按钮下方，会把按钮顶离基线。 -->
          <el-upload
            class="upload__picker"
            :auto-upload="false"
            :limit="1"
            :show-file-list="false"
            :on-change="handleFileChange"
            :on-exceed="handleFileExceed"
            accept=".txt,.md,.docx"
          >
            <el-button name="pick-file">选择文件</el-button>
          </el-upload>
        </div>

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
      <p v-if="selectedFileName" class="documents__hint" data-testid="selected-file">
        已选择：{{ selectedFileName }}
      </p>
      <p v-if="uploadError" class="documents__error" role="alert" data-testid="upload-error">
        {{ uploadError }}
      </p>
    </PanelCard>

    <PanelCard title="文档列表">
      <form class="filters" @submit.prevent="loadFirstPage">
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

      <p
        v-if="documentError || actionError"
        class="documents__error"
        role="alert"
        data-testid="document-error"
      >
        {{ documentError || actionError }}
      </p>
      <p v-else-if="!loading && documents.length === 0" class="documents__empty" data-testid="documents-empty">
        没有符合条件的文档。
      </p>
      <p v-if="processingCount" class="documents__polling" data-testid="document-polling">
        本页 {{ processingCount }} 份文档处理中，列表会自动刷新。
      </p>

      <!--
        列宽一律是「最小宽度」而非固定宽度：el-table 只在各列最小宽度之和大于容器时才出横向滚动条。
        原来的固定值合计 1220px，比侧栏展开（248px）时的主区可用宽度还宽——侧栏折不折都会挂着
        一条水平滑动条。收窄到合计 836px（来源文件同时只展示文件名）后，连侧栏展开的 1200px
        窄屏也落在容器内；多余宽度由 el-table 按列分配，宽度真的不够时才退化成横向滚动。
      -->
      <el-table v-if="documents.length" :data="documents" data-testid="documents-table">
        <el-table-column label="知识类型" prop="knowledge_type" min-width="80" />
        <el-table-column label="标题" prop="title" min-width="100" />
        <el-table-column label="来源文件" min-width="100">
          <template #default="{ row }">{{ fileName(row.source_file) }}</template>
        </el-table-column>
        <el-table-column label="版本" prop="version" min-width="56" />
        <el-table-column label="状态" min-width="120">
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
        <el-table-column label="入库时间" min-width="112">
          <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="分块数" prop="chunk_count" min-width="68" />
        <el-table-column label="过期时间" min-width="112">
          <template #default="{ row }">
            <span v-if="row.expire_at">{{ formatDateTime(row.expire_at) }}</span>
            <span v-else>—</span>
            <el-tag v-if="isNearExpiry(row)" type="warning" size="small" class="documents__expiry">
              即将过期
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="88">
          <template #default="{ row }">
            <el-button size="small" name="delete-document" @click="removeDocument(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 取不到时 `total` 归零，分页条与表格同进同退；越界页 `items` 为空但 `total`
           不变，所以它仍然留着——撤掉它，人就困在那一页上。 -->
      <PaginationBar
        v-if="total > 0"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :disabled="loading"
        @update:page="turnTo"
      />
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

/* el-upload 内部的 .el-upload 是 inline-flex，块级容器里会带基线间隙；开成 flex 消除。 */
.upload__picker {
  display: flex;
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

.documents__hint {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-muted);
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
