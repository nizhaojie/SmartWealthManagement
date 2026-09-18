<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import type { FormInstance, FormRules } from "element-plus";
import { listCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { errorMessage } from "../format";
import { createExternalWorkOrder } from "./api";
import { EXTERNAL_ORDER_TYPES, type ExternalOrderType } from "./types";

// 工单不只来自预警：客户投诉与转人工也走这里建单。
const emit = defineEmits<{ created: [] }>();

const customers = ref<CustomerListItem[]>([]);
const formRef = ref<FormInstance | null>(null);

const form = reactive<{
  orderType: ExternalOrderType;
  customerId: number | null;
  reason: string;
}>({
  orderType: EXTERNAL_ORDER_TYPES[0],
  customerId: null,
  reason: "",
});

const rules: FormRules = {
  orderType: [{ required: true, message: "请选择工单来源", trigger: "change" }],
  reason: [{ required: true, message: "请填写建单理由", trigger: "blur" }],
};

const submitting = ref(false);
const submitError = ref("");

async function submit(): Promise<void> {
  submitError.value = "";
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;

  submitting.value = true;
  try {
    await createExternalWorkOrder({
      orderType: form.orderType,
      customerId: form.customerId,
      reason: form.reason.trim(),
    });
    formRef.value.resetFields();
    emit("created");
  } catch (error) {
    submitError.value = errorMessage(error, "建单失败");
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  try {
    customers.value = await listCustomers();
  } catch {
    // 客户拉不到也能建单（客户字段是可选的），不拦住建单这条路。
    customers.value = [];
  }
});
</script>

<template>
  <PanelCard title="外部工单创建">
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="external"
      @submit.prevent="submit"
    >
      <div class="external__row">
        <el-form-item label="工单来源" prop="orderType">
          <el-select v-model="form.orderType" name="order_type" data-testid="order-type">
            <el-option
              v-for="type in EXTERNAL_ORDER_TYPES"
              :key="type"
              :label="type"
              :value="type"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="关联客户（可选）">
          <el-select
            v-model="form.customerId"
            name="customer_id"
            clearable
            placeholder="不关联客户"
            data-testid="order-customer"
          >
            <el-option
              v-for="customer in customers"
              :key="customer.id"
              :label="customer.real_name"
              :value="customer.id"
            />
          </el-select>
        </el-form-item>
      </div>

      <el-form-item label="建单理由" prop="reason">
        <el-input
          v-model="form.reason"
          name="reason"
          type="textarea"
          :rows="3"
          data-testid="order-reason"
        />
      </el-form-item>

      <p v-if="submitError" class="external__error" role="alert" data-testid="create-error">
        {{ submitError }}
      </p>

      <el-button
        type="primary"
        native-type="submit"
        name="create-work-order"
        data-testid="create-work-order"
        :loading="submitting"
      >
        建单
      </el-button>
    </el-form>
  </PanelCard>
</template>

<style scoped>
.external__row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(calc(var(--wm-space-6) * 7), 1fr));
  gap: 0 var(--wm-space-4);
}

.external__error {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
