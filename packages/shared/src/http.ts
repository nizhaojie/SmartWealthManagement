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
  post<T>(path: string, body?: unknown): Promise<T>;
  postForm<T>(path: string, form: FormData): Promise<T>;
  delete<T>(path: string): Promise<T>;
};

export type HttpClientOptions = {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  getToken?: () => string | null | undefined;
  onUnauthorized?: () => void;
};

export function createHttpClient(options: HttpClientOptions): HttpClient {
  const fetchImpl = options.fetchImpl ?? fetch;
  const prefix = options.baseUrl.replace(/\/$/, "");

  async function request<T>(
    method: "GET" | "PUT" | "POST" | "DELETE",
    path: string,
    body?: unknown,
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
      options.onUnauthorized?.();
    }

    return unwrap(envelope);
  }

  return {
    get<T>(path: string): Promise<T> {
      return request<T>("GET", path);
    },
    put<T>(path: string, body?: unknown): Promise<T> {
      return request<T>("PUT", path, body);
    },
    post<T>(path: string, body?: unknown): Promise<T> {
      return request<T>("POST", path, body);
    },
    postForm<T>(path: string, form: FormData): Promise<T> {
      return request<T>("POST", path, form);
    },
    delete<T>(path: string): Promise<T> {
      return request<T>("DELETE", path);
    },
  };
}
