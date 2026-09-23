/**
 * 查询串拼装：跳过 `undefined` 与空串，空结果不带 `?`。
 *
 * 空串不能发出去：表单里没填的日期是一个 `""`，而 `start_date=""` 到了后端会在参数
 * 校验那一层就变成「参数错误」，整个请求 400——客户只是没填一个可选的筛选项。
 * 空结果同样不能拼出一个孤零零的 `?`，那是另一种形状相同、含义不同的请求。
 *
 * 它与 internal 的 `api/query.ts` 同名同形（issue 02 的「对齐」）：两端各持一份，行为
 * 必须逐字一致——哪一边漂了，那一边的筛选就会少发或多发一个条件，而请求看起来仍然是
 * 成功的。
 */
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
