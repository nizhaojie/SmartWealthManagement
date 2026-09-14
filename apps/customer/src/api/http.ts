import { createHttpClient } from "@wealth/shared";

export const http = createHttpClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
});
