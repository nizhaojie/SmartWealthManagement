// 时效提示：方案不设硬过期（Q7），放行后一直可读；能表达「有多新」的只有
// 出具时间本身，所以页面把日期与距今天数一起写出来。
const DAY_MS = 24 * 60 * 60 * 1000;

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

/** 距今天数。不足一天算今天（0），不写「0 天前」；时间戳不可解析时也不编造天数。 */
export function elapsedDays(releasedAt: string, now: Date = new Date()): number {
  const released = new Date(releasedAt).getTime();
  if (Number.isNaN(released)) return 0;
  return Math.max(0, Math.floor((now.getTime() - released) / DAY_MS));
}

/** 「出具于 X（N 天前）」：X 是出具时间，N 是距今天数。 */
export function timelinessText(releasedAt: string, now: Date = new Date()): string {
  const days = elapsedDays(releasedAt, now);
  const elapsed = days === 0 ? "今天" : `${days} 天前`;
  return `出具于 ${formatDateTime(releasedAt)}（${elapsed}）`;
}
