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
};

export function createHttpClient(options: {
  baseUrl: string;
  fetchImpl?: typeof fetch;
}): HttpClient {
  const fetchImpl = options.fetchImpl ?? fetch;
  const prefix = options.baseUrl.replace(/\/$/, "");

  return {
    async get<T>(path: string): Promise<T> {
      const response = await fetchImpl(`${prefix}${path}`);
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
      return unwrap(envelope);
    },
  };
}
