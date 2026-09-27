<script setup lang="ts">
// 历史记录抽屉：列表 + 详情回看。交互形态借鉴内部工作台数据分析的「历史查询」
// （右侧栏列表 → 只读详情），但载体是抽屉——客服对话页是单列布局，没有常驻侧栏。
//
// 抽屉自己取数：打开时拉第一页列表，点条目拉详情。只读回看，不把历史加载回当前对话
// （「会话不跨登录延续」，历史不进入上下文）。
//
// 列表分页由 `usePagination` 接管（ADR-0024）：会话条数没有上限，翻页只换页码，
// 上一次打开时停在哪一页不带过来。详情是这一场会话本身，与列表的页长无关。
import { ref, watch } from "vue";
import { formatDateTime, PaginationBar, usePagination } from "@wealth/shared";
import CitationPanel from "./CitationPanel.vue";
import CiteChip from "./CiteChip.vue";
import DataAnswerTable from "./DataAnswerTable.vue";
import { splitCitations } from "./citations";
import {
  getCustomerConversation,
  listCustomerConversations,
  type CustomerSessionDetail,
  type CustomerSessionMessage,
  type CustomerSessionSummary,
} from "./history";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const {
  items: sessions,
  total,
  page,
  pageSize,
  loading,
  errorMessage: failedReason,
  goTo,
  reset,
} = usePagination<CustomerSessionSummary>((query) => listCustomerConversations(query), {
  failureMessage: "历史记录加载失败，刷新页面重试。",
});

const selectedId = ref<string | null>(null);
const detail = ref<CustomerSessionDetail | null>(null);
const detailLoading = ref(false);
const detailFailed = ref(false);
const openCitationKey = ref<string | null>(null);

/** 每次打开都从第一页重取：上次停在第 3 页不该带到这一次来（会话不跨登录延续）。 */
async function load(): Promise<void> {
  selectedId.value = null;
  detail.value = null;
  await reset();
}

async function select(sessionId: string): Promise<void> {
  selectedId.value = sessionId;
  detail.value = null;
  detailLoading.value = true;
  detailFailed.value = false;
  openCitationKey.value = null;
  try {
    detail.value = await getCustomerConversation(sessionId);
  } catch {
    detailFailed.value = true;
  } finally {
    detailLoading.value = false;
  }
}

function backToList(): void {
  selectedId.value = null;
  detail.value = null;
  openCitationKey.value = null;
}

function segmentsOf(message: CustomerSessionMessage) {
  return splitCitations(message.content, message.citations);
}

function citationKey(messageIndex: number, citationIndex: number): string {
  return `${messageIndex}:${citationIndex}`;
}

function citationPanelId(messageIndex: number, citationIndex: number): string {
  return `history-citation-panel-${messageIndex}-${citationIndex}`;
}

function isCitationOpen(messageIndex: number, citationIndex: number): boolean {
  return openCitationKey.value === citationKey(messageIndex, citationIndex);
}

function toggleCitation(messageIndex: number, citationIndex: number): void {
  const key = citationKey(messageIndex, citationIndex);
  openCitationKey.value = openCitationKey.value === key ? null : key;
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      void load();
    }
  },
);
</script>

<template>
  <el-drawer
    :model-value="props.open"
    append-to-body
    title="历史记录"
    size="420px"
    @close="emit('close')"
  >
    <!-- 列表视图 -->
    <div v-if="selectedId === null" class="history">
      <p v-if="loading" class="history__status">正在加载历史记录…</p>
      <p
        v-else-if="failedReason"
        class="history__error"
        role="alert"
        data-testid="history-error"
      >
        {{ failedReason }}
      </p>
      <p v-else-if="sessions.length === 0 && total === 0" class="history__status" data-testid="history-empty">
        暂无历史记录
      </p>
      <!-- 有会话但这一页恰好是空的（数据变少、页码跑到了末页之后）：那不是「你还没有历史」 -->
      <p v-else-if="sessions.length === 0" class="history__status" data-testid="history-page-empty">
        这一页没有会话，翻回前面几页看看。
      </p>
      <ul v-else class="history__list">
        <li v-for="entry in sessions" :key="entry.session_id">
          <button
            type="button"
            class="history__item"
            data-testid="history-item"
            @click="select(entry.session_id)"
          >
            <strong class="history__title">{{ entry.title }}</strong>
            <span class="history__meta">
              {{ formatDateTime(entry.ended_at) }} · {{ entry.message_count }} 条消息
            </span>
          </button>
        </li>
      </ul>

      <!-- 取不到时 `total` 归零，分页条与列表同进同退；越界页 `total` 不变，所以它仍然留着 -->
      <PaginationBar
        v-if="total > 0"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :disabled="loading"
        @update:page="goTo"
      />
    </div>

    <!-- 详情视图 -->
    <div v-else class="detail">
      <button type="button" class="detail__back" data-testid="history-back" @click="backToList">
        ← 返回列表
      </button>

      <p v-if="detailLoading" class="history__status">正在加载对话…</p>
      <p v-else-if="detailFailed" class="history__error" role="alert">对话加载失败</p>
      <div v-else-if="detail" class="detail__messages" data-testid="history-detail">
        <article
          v-for="(message, messageIndex) in detail.messages"
          :key="messageIndex"
          class="msg"
          :class="`msg--${message.role}`"
          :data-role="message.role"
        >
          <div class="msg__avatar" aria-hidden="true">
            {{ message.role === "user" ? "我" : "AI" }}
          </div>
          <div class="msg__bubble">
            <p v-if="message.role === 'assistant'" class="msg__text">
              <template v-for="(segment, index) in segmentsOf(message)" :key="index">
                <span v-if="segment.type === 'text'">{{ segment.value }}</span>
                <CiteChip
                  v-else
                  :marker="segment.marker"
                  :open="isCitationOpen(messageIndex, segment.citationIndex)"
                  :panel-id="citationPanelId(messageIndex, segment.citationIndex)"
                  @toggle="toggleCitation(messageIndex, segment.citationIndex)"
                />
              </template>
            </p>
            <p v-else class="msg__text">{{ message.content }}</p>

            <!-- 与实时气泡复用同一件（`DataAnswerTable`）：回看与当时看到的必须是同一张表，
                 没有表（非数据问答那一轮）时就地不渲染，不留空壳。 -->
            <DataAnswerTable
              v-if="message.role === 'assistant' && message.data"
              :data="message.data"
            />

            <span class="msg__time">{{ formatDateTime(message.created_at) }}</span>

            <template v-if="message.role === 'assistant'">
              <template v-for="(citation, index) in message.citations" :key="`panel-${index}`">
                <CitationPanel
                  v-if="isCitationOpen(messageIndex, index)"
                  :citation="citation"
                  :panel-id="citationPanelId(messageIndex, index)"
                />
              </template>
            </template>
          </div>
        </article>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
}

.history__status {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.history__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.history__list {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.history__item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  width: 100%;
  padding: var(--wm-space-2) var(--wm-space-3);
  border: none;
  border-radius: var(--wm-radius-sm);
  background-color: transparent;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.history__item:hover {
  background-color: var(--wm-bg-page);
}

.history__title {
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-weight: 500;
  line-height: 1.6;
}

.history__meta {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.detail__back {
  align-self: flex-start;
  padding: 0;
  border: none;
  background: none;
  color: var(--wm-color-primary-strong);
  font-size: 0.85rem;
  cursor: pointer;
}

.detail__back:hover {
  text-decoration: underline;
}

.detail__messages {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.msg {
  display: flex;
  gap: var(--wm-space-2);
}

.msg--user {
  flex-direction: row-reverse;
}

.msg__avatar {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--wm-space-5);
  height: var(--wm-space-5);
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary-strong);
  font-size: 0.7rem;
  font-weight: 700;
}

.msg__bubble {
  min-width: 0;
  padding: var(--wm-space-2) var(--wm-space-3);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-subtle);
}

.msg__text {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  line-height: 1.75;
  white-space: pre-wrap;
}

.msg__time {
  display: block;
  margin-top: var(--wm-space-1);
  color: var(--wm-text-muted);
  font-size: 0.7rem;
}
</style>
