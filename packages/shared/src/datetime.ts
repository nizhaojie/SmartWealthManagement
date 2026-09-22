/**
 * 时间戳的界面呈现：统一为 `YYYY-MM-DD HH:mm:ss`（本地时区，零填充）。
 *
 * 后端把 datetime 序列化成不带时区的 ISO 串（`2022-04-10T10:30:00`），
 * 而 `toLocaleString()` 会按运行环境的区域设置渲染（`2022/4/10 10:30:00`、
 * `4/10/2022, 10:30:00 AM` 各不相同）——同一个值在不同人屏幕上长得不一样。
 * 时间只服务于「什么时候发生的」，形态必须由我们说死，不交给运行环境。
 *
 * 拿不出可解析的时间时原样奉还：宁可显示后端那句话，也不写「Invalid Date」。
 */
export function formatDateTime(value: string): string {
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return value;
  const pad = (part: number): string => String(part).padStart(2, "0");
  return (
    `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())} ` +
    `${pad(moment.getHours())}:${pad(moment.getMinutes())}:${pad(moment.getSeconds())}`
  );
}
