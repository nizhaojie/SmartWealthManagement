/** 查询串拼装：跳过 `undefined` 与空串，空结果不带 `?`。 */
export function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const result = search.toString();
  return result ? `?${result}` : "";
}
