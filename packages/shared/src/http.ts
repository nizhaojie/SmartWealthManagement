export type Envelope<T> = {
  code: number;
  message: string;
  data: T | null;
  trace_id: string;
};

export class ApiError extends Error {
  readonly code: number;
  readonly traceId: string;

  constructor(envelope: Envelope<unknown>) {
    super(envelope.message);
    this.name = "ApiError";
    this.code = envelope.code;
    this.traceId = envelope.trace_id;
  }
}

export function unwrap<T>(envelope: Envelope<T>): T {
  if (envelope.code !== 200) {
    throw new ApiError(envelope);
  }
  return envelope.data as T;
}

export type HttpClient = {
  get<T>(path: string): Promise<T>;
  put<T>(path: string, body?: unknown): Promise<T>;
  patch<T>(path: string, body?: unknown): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  postForm<T>(path: string, form: FormData): Promise<T>;
  delete<T>(path: string): Promise<T>;
};

export type HttpClientOptions = {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  getToken?: () => string | null | undefined;
  /**
   * 401 时的续期钩子：access token 过期后用它换一张新的，返回是否换到。
   * 换到了就重发一次原请求（重新经 getToken 取令牌）；没换到才算会话失效，
   * 交给 onUnauthorized。不配这个钩子时，401 的处理与从前完全一致。
   */
  renewTokens?: () => Promise<boolean>;
  onUnauthorized?: () => void;
};

export function createHttpClient(options: HttpClientOptions): HttpClient {
  const fetchImpl = options.fetchImpl ?? fetch;
  const prefix = options.baseUrl.replace(/\/$/, "");

  // 首屏常常并发几个请求，它们会一起撞上「access token 刚过期」。共享同一个在途
  // Promise：只兑一次续期，其余等待它的结果，避免过期瞬间打出 N 次刷新。
  let renewalInFlight: Promise<boolean> | null = null;

  function renewTokens(): Promise<boolean> {
    const renew = options.renewTokens;
    if (!renew) {
      return Promise.resolve(false);
    }
    if (!renewalInFlight) {
      renewalInFlight = Promise.resolve()
        .then(renew)
        .catch(() => false)
        .finally(() => {
          renewalInFlight = null;
        });
    }
    return renewalInFlight;
  }

  async function send<T>(
    method: "GET" | "PUT" | "PATCH" | "POST" | "DELETE",
    path: string,
    body: unknown,
    // 续期后只重发一次：再 401 就是真的失效，不能再续，否则两边互相不认时会转圈。
    allowRenewal: boolean,
  ): Promise<T> {
    const headers: Record<string, string> = {};
    const token = options.getToken?.();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const isFormData = body instanceof FormData;
    if (body !== undefined && !isFormData) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetchImpl(`${prefix}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
    });

    let envelope: Envelope<T>;
    try {
      envelope = (await response.json()) as Envelope<T>;
    } catch {
      throw new ApiError({
        code: response.ok ? 500 : response.status,
        message: "服务内部错误",
        data: null,
        trace_id: "",
      });
    }

    if (envelope.code === 401) {
      if (allowRenewal && (await renewTokens())) {
        return send<T>(method, path, body, false);
      }
      options.onUnauthorized?.();
    }

    return unwrap(envelope);
  }

  return {
    get<T>(path: string): Promise<T> {
      return send<T>("GET", path, undefined, true);
    },
    put<T>(path: string, body?: unknown): Promise<T> {
      return send<T>("PUT", path, body, true);
    },
    patch<T>(path: string, body?: unknown): Promise<T> {
      return send<T>("PATCH", path, body, true);
    },
    post<T>(path: string, body?: unknown): Promise<T> {
      return send<T>("POST", path, body, true);
    },
    postForm<T>(path: string, form: FormData): Promise<T> {
      return send<T>("POST", path, form, true);
    },
    delete<T>(path: string): Promise<T> {
      return send<T>("DELETE", path, undefined, true);
    },
  };
}
