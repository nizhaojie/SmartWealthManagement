import { http } from "../api/http";
import type { CustomerAssets, LookThrough } from "./types";

export function getAssets(): Promise<CustomerAssets> {
  return http.get<CustomerAssets>("/api/customer/assets");
}

export function getHoldingLookThrough(productCode: string): Promise<LookThrough> {
  const path = `/api/customer/assets/holdings/${encodeURIComponent(productCode)}/look-through`;
  return http.get<LookThrough>(path);
}
