<script setup lang="ts">
import { ref, watch } from "vue";
import { PaginationBar, usePagination } from "@wealth/shared";
import { formatDateTime } from "../format";
import { listAnalyticsHistory } from "./api";
import type { AnalyticsHistoryItem } from "./types";

/**
 * 历史查询抽屉：留痕表里的一页，一条记录就是一次提问（ADR-0024）。
 *
 * **一个态**：留痕一行只有问题、状态、时间、行数、截断、错误码与它生成的那句查询，
 * 为这点增量再分「列表 ⇄ 详情」两态是照客服的模板走，不是按内容量走——SQL 因此行内折叠。
 *
 * 取数归抽屉自己。搬进抽屉之前它常驻右栏，数据由页面拉好传进来：右栏是壳层的常驻位，
 * 需要一条跨组件通道；抽屉只有一个入口——打开就取，那条通道就没有存在的理由了。
 *
 * 开合是双向的（`v-model:open`）：抽屉会被**人**从自己那一侧关掉——关闭按钮、Esc、点遮罩，
 * 父组件的 `open` 必须跟上，否则关一次之后顶栏那个入口就点不开了。
 */
const open = defineModel<boolean>({ required: true });

const emit = defineEmits<{
  /** 「再问一次」：把这句话送回输入框，发不发由员工决定。 */
  reuse: [question: string];
}>();

/**
 * 三条关闭路径（关闭按钮 / Esc / 点遮罩）都在 `beforeClose` 收口，这是 `el-drawer` 上每次
 * 关闭都会经过的那个钩子。只监听 `close` 不够：这个版本从抽屉那一侧关上时一个事件都不派发
 * （`close` 与 `update:modelValue` 都挂在 leave 过渡的钩子上，而 `v-show` 这一路并没有走过渡
 * ——关闭按钮按下去，遮罩是立刻 `display: none` 的，事件一个也没有），父组件的 `open` 会一直
 * 停在 true：关一次之后顶栏那个入口就点不开了。因此在这里显式把模型置回 false，再放行关闭。
 */
function handleClose(done: () => void): void {
  open.value = false;
  done();
}

const {
  items: history,
  total,
  page,
  pageSize,
  loading,
  errorMessage: historyError,
  goTo,
  reset,
} = usePagination<AnalyticsHistoryItem>((query) => listAnalyticsHistory(query));

// 展开的是哪一条的 SQL。一次只开一条：抽屉本来就窄，两条 SQL 同时铺开反而看不出来谁是谁。
const openSqlId = ref<number | null>(null);

/** 每次打开都从第一页重取：上次停在第 3 页不该带到这一次来（与客服的历史抽屉同口径）。 */
watch(open, (visible) => {
  if (!visible) return;
  openSqlId.value = null;
  void reset();
});

function isSqlOpen(id: number): boolean {
  return openSqlId.value === id;
}

function toggleSql(id: number): void {
  openSqlId.value = isSqlOpen(id) ? null : id;
}

/** 返回行数：失败的那几条在留痕里就是 `null`——不拿 0 冒充，0 行是一次成功的空结果。 */
function rowsLabel(entry: AnalyticsHistoryItem): string {
  return entry.row_count === null ? "返回行数 —" : `返回 ${entry.row_count} 行`;
}
</script>

<template>
  <el-drawer
    :model-value="open"
    append-to-body
    title="历史查询"
    size="480px"
    :before-close="handleClose"
  >
    <div class="history" data-testid="history-drawer">
      <p v-if="loading" class="history__hint">正在加载历史查询…</p>
      <p
        v-else-if="historyError"
        class="history__error"
        role="alert"
        data-testid="history-error"
      >
        {{ historyError }}
      </p>
      <p
        v-else-if="history.length === 0 && total === 0"
        class="history__hint"
        data-testid="history-empty"
      >
        还没有历史查询
      </p>
      <!-- 有留痕但这一页恰好是空的（页码跑到了末页之后）：那不是「你还没问过」 -->
      <p v-else-if="history.length === 0" class="history__hint" data-testid="history-page-empty">
        这一页没有历史查询，翻回前面几页看看。
      </p>
      <ul v-else class="history__list">
        <li
          v-for="entry in history"
          :key="entry.id"
          class="history__item"
          :data-testid="`history-item-${entry.id}`"
        >
          <p class="history__question">{{ entry.question }}</p>
          <p class="history__meta">
            <span>{{ entry.status }}</span>
            <span aria-hidden="true">·</span>
            <span>{{ formatDateTime(entry.create_time) }}</span>
            <span aria-hidden="true">·</span>
            <span>{{ rowsLabel(entry) }}</span>
            <template v-if="entry.truncated">
              <span aria-hidden="true">·</span>
              <span class="history__truncated">已截断</span>
            </template>
            <template v-if="entry.error_code !== null">
              <span aria-hidden="true">·</span>
              <span class="history__error-code">错误码 {{ entry.error_code }}</span>
            </template>
          </p>

          <div class="history__actions">
            <button
              type="button"
              class="history__action"
              :data-testid="`history-sql-toggle-${entry.id}`"
              :aria-expanded="isSqlOpen(entry.id)"
              @click="toggleSql(entry.id)"
            >
              {{ isSqlOpen(entry.id) ? "收起生成的查询" : "查看生成的查询" }}
            </button>
            <button
              type="button"
              class="history__action"
              :data-testid="`history-reuse-${entry.id}`"
              @click="emit('reuse', entry.question)"
            >
              再问一次
            </button>
          </div>

          <!-- 留痕里可能没有查询：被拒绝的那几次压根没生成出来，不补一句假的 -->
          <pre
            v-if="isSqlOpen(entry.id)"
            class="history__sql"
            :data-testid="`history-sql-${entry.id}`"
          >{{ entry.sql ?? "—" }}</pre>
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

      <p class="history__note" data-testid="history-note">
        留痕只保存问题、生成的查询与状态，不保存结果集；要看当前数据请重新提问。
      </p>
    </div>
  </el-drawer>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.history__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}

.history__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
  line-height: 1.7;
}

.history__list {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.history__item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  padding: var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外：一条留痕是一张卡片，靠描边分开而不是靠底色 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-card);
}

.history__question {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-weight: 500;
  line-height: 1.6;
}

.history__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-1);
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
}

.history__truncated {
  color: var(--wm-color-warning);
}

.history__error-code {
  color: var(--wm-color-danger);
}

.history__actions {
  display: flex;
  gap: var(--wm-space-3);
}

/* 行内动作是次级出口：不占一个按钮的份量，但仍要看得见可点（与抽屉的「返回列表」同一手法） */
.history__action {
  padding: 0;
  border: none;
  background: none;
  color: var(--wm-color-primary-strong);
  font-family: inherit;
  font-size: 0.78rem;
  cursor: pointer;
}

.history__action:hover {
  text-decoration: underline;
}

.history__sql {
  margin: 0;
  padding: var(--wm-space-3);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-text-primary);
  font-family: var(--wm-font-mono);
  font-size: 0.78rem;
  line-height: 1.7;
  overflow-x: auto;
  white-space: pre-wrap;
}

/* 脚注走豁免档（--wm-text-placeholder 仅限 placeholder 与装饰） */
.history__note {
  margin: 0;
  color: var(--wm-text-placeholder);
  font-size: 0.78rem;
  line-height: 1.7;
}
</style>
