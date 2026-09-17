import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
// 令牌在 EP 样式之后加载,:root 同名覆盖才能压过 --el-* 默认值。
import "@wealth/shared/tokens.css";
import App from "./App.vue";

createApp(App).use(ElementPlus).mount("#app");
