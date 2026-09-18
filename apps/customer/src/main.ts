import { createApp } from "vue";
import ElementPlus from "element-plus";
import { createPinia } from "pinia";
import "element-plus/dist/index.css";
// 令牌在 EP 样式之后加载，:root 同名覆盖才能压过 --el-* 默认值。
import "@wealth/shared/tokens.css";
import App from "./App.vue";
import { router } from "./router";

// Pinia 先于路由注册：守卫要读登录态。
createApp(App).use(createPinia()).use(ElementPlus).use(router).mount("#app");
