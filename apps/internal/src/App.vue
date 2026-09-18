<script setup lang="ts">
import { watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

// 会话在页面停留期间失效（任一接口回 401，令牌被清掉）时，不把人留在必然报错的页面上。
// 导航时的门控在 router 守卫里，这一条补的是「人已经进来了」之后的那半程。
watch(
  () => auth.isAuthenticated,
  (authenticated) => {
    if (!authenticated && !route.meta.public) {
      void router.push({ name: "login" });
    }
  },
);
</script>

<template>
  <router-view />
</template>
