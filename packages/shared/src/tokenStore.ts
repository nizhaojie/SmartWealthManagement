import { ref, type Ref } from "vue";

export type StoredTokens = {
  accessToken: string;
  refreshToken: string;
};

export type TokenStore = {
  tokens: Ref<StoredTokens | null>;
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  setTokens: (next: StoredTokens) => void;
  /**
   * 只换 access token，保留手里的 refresh token。会话续期走这条路：
   * 刷新接口只发新的 access token，整对覆盖会把还没过期的 refresh token 抹掉。
   * 没有会话时（未登录）忽略——无从知道该配哪一张 refresh token。
   */
  setAccessToken: (accessToken: string) => void;
  clearTokens: () => void;
};

export function createTokenStore(storageKey: string): TokenStore {
  function load(): StoredTokens | null {
    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw) as StoredTokens;
    } catch {
      return null;
    }
  }

  const tokens = ref<StoredTokens | null>(load());

  return {
    tokens,
    getAccessToken: () => tokens.value?.accessToken ?? null,
    getRefreshToken: () => tokens.value?.refreshToken ?? null,
    setTokens(next: StoredTokens) {
      tokens.value = next;
      localStorage.setItem(storageKey, JSON.stringify(next));
    },
    setAccessToken(accessToken: string) {
      if (!tokens.value) {
        return;
      }
      const next = { ...tokens.value, accessToken };
      tokens.value = next;
      localStorage.setItem(storageKey, JSON.stringify(next));
    },
    clearTokens() {
      tokens.value = null;
      localStorage.removeItem(storageKey);
    },
  };
}
