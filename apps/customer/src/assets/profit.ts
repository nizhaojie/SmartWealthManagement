/**
 * 红涨绿跌（中国金融惯例）：应用侧只按符号挂类名，颜色只出自 --wm-color-up / --wm-color-down。
 * 返回空串表示「既不是涨也不是跌」，交给默认文字色。
 */
export function profitClass(value: string): "profit-up" | "profit-down" | "" {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount === 0) {
    return "";
  }
  return amount > 0 ? "profit-up" : "profit-down";
}
