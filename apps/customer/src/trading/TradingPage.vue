<script setup lang="ts">
/**
 * 「交易」：客户侧第一个写操作页面。
 *
 * 它独立于只读的资产页，而不是长在资产页里——交易与看资产是两件事，把它们并在一起，
 * 客户会以为「买入」只是资产页的一个小动作。这里是可用余额 + 三个入口（申购 / 赎回 /
 * 转账），每一笔都由受理侧校验后当场成交（ADR-0018）：
 *
 * - 校验过不了（余额不足、越级、未测评、低于起投金额、不在售、份额不足）→ 渲染受理侧原文；
 * - 校验过了 → 成交、余额与持仓随之变动，这里把它们刷新一遍。
 *
 * 三条路径都走同一个入海口进风控（`app.risk_monitoring.alerting`），界面上看不见它，
 * 也不该看见——风控是事后监测，不阻断本页的任何操作。
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ApiError, PageHeader, PanelCard, StatCard } from "@wealth/shared";
import { getAssets } from "../assets/api";
import type { Holding, TransactionRecord } from "../assets/types";
import { useAvailableBalance } from "../funding/useAvailableBalance";
import { listProducts } from "../products/api";
import type { Product } from "../products/types";
import FailureNotice from "./FailureNotice.vue";
import { purchase, redeem, transfer } from "./api";
import { describeAcceptanceFailure, type AcceptanceFailure } from "./failure";

const BALANCE_HINT =
  "可用余额是你在这里能立即动用的钱，与画像里的总资产不是一回事。申购与转账扣减它，赎回增加它。";

const { balance, error: balanceError, load: loadBalance } = useAvailableBalance();

const holdings = ref<Holding[]>([]);
const holdingsLoaded = ref(false);
const holdingsError = ref("");
const productsLoaded = ref(false);
const productsError = ref("");
const products = ref<Product[]>([]);

const purchaseForm = reactive({ product_code: "", amount: "" });
const redemptionForm = reactive({ product_code: "", shares: "" });
const transferForm = reactive({ payee_name: "", payee_account: "", amount: "" });

const purchaseSubmitting = ref(false);
const purchaseFailure = ref<AcceptanceFailure | null>(null);
const purchaseDone = ref<TransactionRecord | null>(null);

const redemptionSubmitting = ref(false);
const redemptionFailure = ref<AcceptanceFailure | null>(null);
const redemptionDone = ref<TransactionRecord | null>(null);

const transferSubmitting = ref(false);
const transferFailure = ref<AcceptanceFailure | null>(null);
const transferDone = ref<TransactionRecord | null>(null);

const selectedHolding = computed(
  () =>
    holdings.value.find((holding) => holding.product_code === redemptionForm.product_code) ?? null,
);

// 拉不到持仓与拉不到在售产品都各自留一句原因：接口故障不能说成「你没有可赎回的持仓」，
// 那会让客户去查一个并不存在的问题（「还没有」不是一种错误）。
async function loadHoldings(): Promise<void> {
  holdingsError.value = "";
  try {
    holdings.value = (await getAssets()).holdings;
  } catch (error) {
    holdings.value = [];
    holdingsError.value = error instanceof ApiError ? error.message : "持仓信息加载失败";
  } finally {
    holdingsLoaded.value = true;
  }
}

async function loadProducts(): Promise<void> {
  productsError.value = "";
  try {
    products.value = (await listProducts()).products;
  } catch (error) {
    products.value = [];
    productsError.value = error instanceof ApiError ? error.message : "在售产品加载失败";
  } finally {
    productsLoaded.value = true;
  }
}

// 选中一只持仓就把份额默认填成它的全部份额：客户最常做的是把钱取回来，要改也能改。
watch(
  () => redemptionForm.product_code,
  () => {
    redemptionForm.shares = selectedHolding.value?.shares ?? "";
  },
);

async function submitPurchase(): Promise<void> {
  purchaseFailure.value = null;
  purchaseDone.value = null;
  purchaseSubmitting.value = true;
  try {
    const result = await purchase(purchaseForm);
    balance.value = result.available_balance;
    purchaseDone.value = result.transaction;
    purchaseForm.amount = "";
    // 买完多了一只持仓（或加仓），赎回的候选跟着变。
    await loadHoldings();
  } catch (error) {
    purchaseFailure.value = describeAcceptanceFailure(error, "申购失败，请稍后重试");
  } finally {
    purchaseSubmitting.value = false;
  }
}

async function submitRedemption(): Promise<void> {
  redemptionFailure.value = null;
  redemptionDone.value = null;
  redemptionSubmitting.value = true;
  try {
    const result = await redeem(redemptionForm);
    balance.value = result.available_balance;
    redemptionDone.value = result.transaction;
    redemptionForm.product_code = "";
    redemptionForm.shares = "";
    await loadHoldings();
  } catch (error) {
    redemptionFailure.value = describeAcceptanceFailure(error, "赎回失败，请稍后重试");
  } finally {
    redemptionSubmitting.value = false;
  }
}

async function submitTransfer(): Promise<void> {
  transferFailure.value = null;
  transferDone.value = null;
  transferSubmitting.value = true;
  try {
    const result = await transfer(transferForm);
    balance.value = result.available_balance;
    transferDone.value = result.transaction;
    transferForm.payee_name = "";
    transferForm.payee_account = "";
    transferForm.amount = "";
  } catch (error) {
    transferFailure.value = describeAcceptanceFailure(error, "转账失败，请稍后重试");
  } finally {
    transferSubmitting.value = false;
  }
}

onMounted(() => {
  void Promise.all([loadBalance(), loadHoldings(), loadProducts()]);
});
</script>

<template>
  <div class="trading">
    <PageHeader title="交易" :breadcrumb="['客户视图', '交易']" />

    <div class="trading__balance" data-testid="available-balance">
      <StatCard title="可用余额（元）" :value="balance" accent="primary" />
    </div>
    <p class="trading__hint">{{ BALANCE_HINT }}</p>
    <p v-if="balanceError" class="trading__error" role="alert" data-testid="balance-error">
      {{ balanceError }}
    </p>

    <PanelCard title="申购">
      <form class="trade-form" data-testid="purchase-form" @submit.prevent="submitPurchase">
        <label class="trade-form__field">
          <span class="trade-form__label">产品</span>
          <el-select
            v-model="purchaseForm.product_code"
            name="purchase-product"
            placeholder="选择要申购的产品"
            filterable
          >
            <el-option
              v-for="product in products"
              :key="product.product_code"
              :label="`${product.product_name}（${product.product_code}）`"
              :value="product.product_code"
            />
          </el-select>
        </label>
        <label class="trade-form__field">
          <span class="trade-form__label">金额（元）</span>
          <el-input
            v-model="purchaseForm.amount"
            name="purchase-amount"
            inputmode="decimal"
            placeholder="请输入申购金额"
          />
        </label>
        <el-button name="submit-purchase" native-type="submit" :loading="purchaseSubmitting">
          确认申购
        </el-button>
      </form>

      <p v-if="productsError" class="trading__error" role="alert" data-testid="products-error">
        {{ productsError }}
      </p>
      <p
        v-else-if="productsLoaded && products.length === 0"
        class="trading__empty"
        data-testid="purchase-empty"
      >
        当前没有在售的产品可供申购。可以过一会儿再来，或联系你的客户经理。
      </p>
      <p v-if="purchaseDone" class="trading__done" data-testid="purchase-done">
        申购成功，流水号 {{ purchaseDone.transaction_no }}，成交金额 {{ purchaseDone.amount }} 元。
      </p>
      <div v-if="purchaseFailure" data-testid="purchase-failure">
        <FailureNotice :failure="purchaseFailure" />
      </div>
    </PanelCard>

    <PanelCard title="赎回">
      <p v-if="holdingsError" class="trading__error" role="alert" data-testid="holdings-error">
        {{ holdingsError }}
      </p>
      <p v-else-if="!holdingsLoaded" class="trading__status">正在加载持仓…</p>
      <p v-else-if="holdings.length === 0" class="trading__empty" data-testid="redemption-empty">
        你当前没有可赎回的持仓。买入后，这里会列出每一只持仓可赎回的份额。
      </p>

      <form v-else class="trade-form" data-testid="redemption-form" @submit.prevent="submitRedemption">
        <label class="trade-form__field">
          <span class="trade-form__label">持仓产品</span>
          <el-select
            v-model="redemptionForm.product_code"
            name="redemption-product"
            placeholder="选择要赎回的持仓"
          >
            <el-option
              v-for="holding in holdings"
              :key="holding.product_code"
              :label="`${holding.product_name}（${holding.product_code}）可赎回 ${holding.shares} 份`"
              :value="holding.product_code"
            />
          </el-select>
        </label>
        <label class="trade-form__field">
          <span class="trade-form__label">赎回份额</span>
          <el-input
            v-model="redemptionForm.shares"
            name="redemption-shares"
            inputmode="decimal"
            placeholder="请输入赎回份额"
          />
        </label>
        <el-button name="submit-redemption" native-type="submit" :loading="redemptionSubmitting">
          确认赎回
        </el-button>
      </form>

      <p v-if="redemptionDone" class="trading__done" data-testid="redemption-done">
        赎回成功，流水号 {{ redemptionDone.transaction_no }}，成交金额 {{ redemptionDone.amount }} 元。
      </p>
      <div v-if="redemptionFailure" data-testid="redemption-failure">
        <FailureNotice :failure="redemptionFailure" />
      </div>
    </PanelCard>

    <PanelCard title="转账">
      <form class="trade-form" data-testid="transfer-form" @submit.prevent="submitTransfer">
        <label class="trade-form__field">
          <span class="trade-form__label">收款人姓名</span>
          <el-input
            v-model="transferForm.payee_name"
            name="transfer-payee-name"
            placeholder="请输入收款人姓名"
          />
        </label>
        <label class="trade-form__field">
          <span class="trade-form__label">收款人账号</span>
          <el-input
            v-model="transferForm.payee_account"
            name="transfer-payee-account"
            placeholder="请输入收款人账号"
          />
        </label>
        <label class="trade-form__field">
          <span class="trade-form__label">金额（元）</span>
          <el-input
            v-model="transferForm.amount"
            name="transfer-amount"
            inputmode="decimal"
            placeholder="请输入转账金额"
          />
        </label>
        <el-button name="submit-transfer" native-type="submit" :loading="transferSubmitting">
          确认转账
        </el-button>
      </form>

      <p v-if="transferDone" class="trading__done" data-testid="transfer-done">
        转账成功，流水号 {{ transferDone.transaction_no }}，收款人 {{ transferDone.payee_name }}。
      </p>
      <div v-if="transferFailure" data-testid="transfer-failure">
        <FailureNotice :failure="transferFailure" />
      </div>
    </PanelCard>
  </div>
</template>

<style scoped>
.trading {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.trading__balance {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(calc(var(--wm-space-6) * 7), 1fr));
  gap: var(--wm-space-4);
}

.trading__hint,
.trading__status,
.trading__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.trading__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.trading__done {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.trade-form {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
}

.trade-form__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.trade-form__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.trade-form :deep(.el-select) {
  width: 100%;
}
</style>
