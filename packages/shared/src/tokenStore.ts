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
    clearTokens() {
      tokens.value = null;
      localStorage.removeItem(storageKey);
    },
  };
}
