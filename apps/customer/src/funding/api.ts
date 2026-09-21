// 可用余额的只读出口。客户由令牌圈定，请求里没有客户标识——
// 塞进来的不作数，服务端只认凭证（客户可见视图的边界）。
import { http } from "../api/http";
import type { FundingAccount } from "./types";

export function getFundingAccount(): Promise<FundingAccount> {
  return http.get<FundingAccount>("/api/customer/funding-account");
}
