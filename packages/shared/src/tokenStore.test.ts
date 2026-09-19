// @vitest-environment jsdom
// 续期只换 access token：整对覆盖会把手里还没过期的 refresh token 抹掉，
// 15 分钟后再无人可续，人就真被踢下线了。
import { beforeEach, describe, expect, it } from "vitest";
import { createTokenStore } from "./tokenStore";

beforeEach(() => {
  localStorage.clear();
});

describe("createTokenStore", () => {
  it("setAccessToken 只换 access token，保留 refresh token", () => {
    const store = createTokenStore("test-auth");
    store.setTokens({ accessToken: "expired", refreshToken: "refresh-1" });

    store.setAccessToken("fresh");

    expect(store.getAccessToken()).toBe("fresh");
    expect(store.getRefreshToken()).toBe("refresh-1");
    expect(JSON.parse(localStorage.getItem("test-auth") as string)).toEqual({
      accessToken: "fresh",
      refreshToken: "refresh-1",
    });
  });

  it("没有会话时忽略：无从知道该配哪一张 refresh token", () => {
    const store = createTokenStore("test-auth");

    store.setAccessToken("fresh");

    expect(store.getAccessToken()).toBeNull();
    expect(localStorage.getItem("test-auth")).toBeNull();
  });
});
