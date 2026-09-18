import { createApp } from "vue";
import ElementPlus from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import { createPinia } from "pinia";
import "element-plus/dist/index.css";
// 令牌在 EP 样式之后加载,:root 同名覆盖才能压过 --el-* 默认值。
import "@wealth/shared/tokens.css";
import App from "./App.vue";
import { router } from "./router";

// Pinia 先于路由注册：守卫里要读登录态。
// 全局挂中文语言包：日期选择器等组件默认英文，需显式切换。
createApp(App).use(createPinia()).use(ElementPlus, { locale: zhCn }).use(router).mount("#app");
