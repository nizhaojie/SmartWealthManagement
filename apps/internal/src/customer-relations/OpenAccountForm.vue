<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import type { FormInstance, FormRules } from "element-plus";
import { errorMessage } from "../format";
import { openAccount, type OpenAccountInput } from "./api";
import {
  ANNUAL_INCOME_RANGES,
  CUSTOMER_LEVELS,
  ID_NUMBER_PATTERN,
  INVESTMENT_EXPERIENCES,
  MIN_PASSWORD_LENGTH,
  PHONE_PATTERN,
  TARGET_ALLOCATION_CATEGORIES,
  TARGET_ALLOCATION_TOTAL,
  targetAllocationError,
  targetAllocationTotal,
} from "./onboarding";

const emit = defineEmits<{ created: [] }>();

const formRef = ref<FormInstance | null>(null);

const form = reactive({
  username: "",
  password: "",
  real_name: "",
  id_number: "",
  phone: "",
  customer_level: CUSTOMER_LEVELS[0] as string,
  annual_income_range: ANNUAL_INCOME_RANGES[0] as string,
  total_assets: "",
  investment_experience: INVESTMENT_EXPERIENCES[0] as string,
  product_preference: "",
});

// 目标配置可选：五项都为 0 时视为「没有填」，不发这个字段。
const targetAllocation = reactive<Record<string, number>>(
  Object.fromEntries(TARGET_ALLOCATION_CATEGORIES.map((category) => [category, 0])),
);

// 合计实时显示：五项各自在 0-100 之内不等于它们合起来是一个比例，
// 用户要能看见自己还差多少，而不是提交之后被后端退回来。
const allocationTotal = computed(() => targetAllocationTotal(targetAllocation));
const allocationProblem = computed(() => targetAllocationError(targetAllocation));

const rules: FormRules = {
  username: [{ required: true, message: "请填写登录账号", trigger: "blur" }],
  password: [
    { required: true, message: "请填写初始密码", trigger: "blur" },
    { min: MIN_PASSWORD_LENGTH, message: `密码至少 ${MIN_PASSWORD_LENGTH} 位`, trigger: "blur" },
  ],
  real_name: [{ required: true, message: "请填写客户姓名", trigger: "blur" }],
  id_number: [
    { required: true, message: "请填写证件号码", trigger: "blur" },
    { pattern: ID_NUMBER_PATTERN, message: "证件号码为 18 位（末位可为 X）", trigger: "blur" },
  ],
  phone: [
    { required: true, message: "请填写手机号", trigger: "blur" },
    { pattern: PHONE_PATTERN, message: "手机号必须是 11 位数字", trigger: "blur" },
  ],
  customer_level: [{ required: true, message: "请选择客户分层", trigger: "change" }],
  annual_income_range: [{ required: true, message: "请选择年收入区间", trigger: "change" }],
  investment_experience: [{ required: true, message: "请选择投资经验", trigger: "change" }],
  total_assets: [
    {
      validator: (_rule, value, callback) => {
        if (value === "" || value === null || value === undefined) {
          callback(new Error("请填写资产规模"));
          return;
        }
        const amount = Number(value);
        if (!Number.isFinite(amount) || amount < 0) {
          callback(new Error("资产规模必须是不小于 0 的数字"));
          return;
        }
        callback();
      },
      trigger: "blur",
    },
  ],
};

const submitting = ref(false);
const submitError = ref("");

function allocationPayload(): Record<string, number> | null {
  const entries = Object.entries(targetAllocation).filter(([, value]) => value > 0);
  return entries.length ? { ...targetAllocation } : null;
}

function preferencePayload(): Record<string, unknown> | null | undefined {
  const text = form.product_preference.trim();
  if (!text) return null;
  const parsed: unknown = JSON.parse(text);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("产品偏好必须是 JSON 对象");
  }
  return parsed as Record<string, unknown>;
}

async function submit(): Promise<void> {
  submitError.value = "";
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;

  // 目标配置是比例：合计不为 100 就不是一个能拿来比较的基线。错误显示在它自己那一块
  // 下面（`allocationProblem`，随输入实时更新），因此这里只是不放行——两处各写一遍
  // 同一句话会让人以为是两个问题。
  if (allocationProblem.value) return;

  let productPreference: Record<string, unknown> | null;
  try {
    productPreference = preferencePayload() ?? null;
  } catch (error) {
    submitError.value = errorMessage(error, "产品偏好必须是 JSON 对象");
    return;
  }

  const input: OpenAccountInput = {
    username: form.username.trim(),
    password: form.password,
    real_name: form.real_name.trim(),
    id_number: form.id_number.trim(),
    phone: form.phone.trim(),
    customer_level: form.customer_level,
    annual_income_range: form.annual_income_range,
    total_assets: form.total_assets.trim(),
    investment_experience: form.investment_experience,
    target_allocation: allocationPayload(),
    product_preference: productPreference,
  };

  submitting.value = true;
  try {
    await openAccount(input);
    formRef.value.resetFields();
    for (const category of TARGET_ALLOCATION_CATEGORIES) {
      targetAllocation[category] = 0;
    }
    emit("created");
  } catch (error) {
    // 后端的具体原因（账号已存在、证件已开户……）直接透传，不盖成一句套话。
    submitError.value = errorMessage(error, "开户失败");
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <PanelCard title="开户">
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="open-account"
      @submit.prevent="submit"
    >
      <div class="open-account__grid">
        <el-form-item label="登录账号" prop="username">
          <el-input v-model="form.username" name="username" placeholder="客户登录用账号" />
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input v-model="form.password" name="password" type="password" placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="姓名" prop="real_name">
          <el-input v-model="form.real_name" name="real_name" />
        </el-form-item>
        <el-form-item label="证件号码" prop="id_number">
          <el-input v-model="form.id_number" name="id_number" placeholder="18 位身份证号" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" name="phone" placeholder="11 位手机号" />
        </el-form-item>
        <el-form-item label="客户分层" prop="customer_level">
          <el-select v-model="form.customer_level" name="customer_level">
            <el-option
              v-for="level in CUSTOMER_LEVELS"
              :key="level"
              :label="level"
              :value="level"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="年收入区间" prop="annual_income_range">
          <el-select v-model="form.annual_income_range" name="annual_income_range">
            <el-option
              v-for="range in ANNUAL_INCOME_RANGES"
              :key="range"
              :label="range"
              :value="range"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="资产规模（元）" prop="total_assets">
          <el-input v-model="form.total_assets" name="total_assets" inputmode="decimal" />
        </el-form-item>
        <el-form-item label="投资经验" prop="investment_experience">
          <el-select v-model="form.investment_experience" name="investment_experience">
            <el-option
              v-for="experience in INVESTMENT_EXPERIENCES"
              :key="experience"
              :label="experience"
              :value="experience"
            />
          </el-select>
        </el-form-item>
      </div>

      <fieldset class="open-account__optional">
        <legend class="open-account__legend">可选：目标配置（各类资产占比，%）</legend>
        <p class="open-account__allocation-total">
          <span>合计</span>
          <span
            class="open-account__allocation-sum"
            :class="{ 'is-invalid': allocationProblem !== null }"
            data-testid="target-allocation-total"
          >
            {{ allocationTotal }}%
          </span>
          <span class="open-account__legend">
            （各项占比合计须为 {{ TARGET_ALLOCATION_TOTAL }}%，全为 0 视为不填）
          </span>
        </p>
        <div class="open-account__allocation">
          <label
            v-for="category in TARGET_ALLOCATION_CATEGORIES"
            :key="category"
            class="open-account__allocation-item"
          >
            <span>{{ category }}</span>
            <el-input-number
              v-model="targetAllocation[category]"
              :min="0"
              :max="100"
              size="small"
            />
          </label>
        </div>

        <p
          v-if="allocationProblem"
          class="open-account__error"
          role="alert"
          data-testid="target-allocation-error"
        >
          {{ allocationProblem }}
        </p>

        <label class="open-account__preference">
          <span class="open-account__legend">可选：产品偏好（JSON 对象）</span>
          <el-input
            v-model="form.product_preference"
            name="product_preference"
            type="textarea"
            :rows="2"
            placeholder='例如 {"类型": ["债券基金"]}'
          />
        </label>
      </fieldset>

      <p v-if="submitError" class="open-account__error" role="alert" data-testid="open-account-error">
        {{ submitError }}
      </p>

      <div class="open-account__actions">
        <el-button
          type="primary"
          native-type="submit"
          name="submit-open-account"
          data-testid="submit-open-account"
          :loading="submitting"
        >
          开户
        </el-button>
      </div>
    </el-form>
  </PanelCard>
</template>

<style scoped>
.open-account__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(calc(var(--wm-space-6) * 7), 1fr));
  gap: 0 var(--wm-space-4);
}

.open-account__optional {
  margin: var(--wm-space-2) 0 0;
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
}

.open-account__legend {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.open-account__allocation-total {
  display: flex;
  align-items: baseline;
  gap: var(--wm-space-2);
  margin: var(--wm-space-3) 0 0;
  font-size: 0.85rem;
}

.open-account__allocation-sum {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.open-account__allocation-sum.is-invalid {
  color: var(--wm-color-danger);
}

.open-account__allocation {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-3) var(--wm-space-4);
  margin: var(--wm-space-3) 0;
}

.open-account__allocation-item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  font-size: 0.8rem;
  color: var(--wm-text-muted);
}

.open-account__preference {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
}

.open-account__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.open-account__actions {
  margin-top: var(--wm-space-4);
}
</style>
