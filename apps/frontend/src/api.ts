export type PromptStatus = "active" | "superseded" | "candidate" | "rejected" | "abandoned";

export interface PromptVersion {
  id: number;
  parent_id: number | null;
  status: PromptStatus;
  change_reason: string;
  content: string;
  created_at: string;
}

export interface TriageRecord {
  intent: string;
  urgency: string;
}

export interface ProcessOk {
  request_id: string;
  sample_id: string;
  prompt_version: number;
  record: TriageRecord;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
}

export interface ProcessOutcome {
  status: number;
  requestId: string | null;
  replayed: boolean;
  retryAfter: string | null;
  ok: ProcessOk | null;
  error: ApiErrorBody | null;
}

export interface Page<T> {
  total: number;
  items: T[];
}

export interface Sample {
  id: string;
  request_id: string;
  prompt_version_id: number;
  input: string;
  output: TriageRecord;
  provider: string;
  model: string;
  model_settings: string;
  created_at: string;
}

export interface LlmCall {
  id: string;
  request_id: string;
  sample_id: string | null;
  review_id: string | null;
  prompt_version_id: number | null;
  operation: string;
  provider: string;
  model: string;
  provider_request_id: string | null;
  attempt: number;
  status: "running" | "success" | "error" | "timeout";
  input_tokens: number | null;
  output_tokens: number | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface RequestSummary {
  request_id: string;
  started_at: string;
  ended_at: string;
  attempts: number;
  total_duration_ms: number | null;
  sample_id: string | null;
  provider: string;
  model: string;
  prompt_version_id: number | null;
  status: LlmCall["status"];
  error_code: string | null;
}

export interface IdempotencyRecord {
  endpoint: string;
  key: string;
  status: "processing" | "completed" | "retryable_failed" | "failed";
  sample_id: string | null;
  lease_expires_at: string | null;
  response_status: number | null;
  response_body: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface RequestDetail {
  request_id: string;
  calls: LlmCall[];
  samples: Sample[];
  idempotency: IdempotencyRecord[];
}

export type ProviderName = "simulator" | "ollama";

export interface ProviderState {
  current: ProviderName;
  profiles: { name: ProviderName; base_url: string; processing_model: string; judge_model: string }[];
  warm_up: string | null;
  breakers: Record<string, string>;
}

export const FAULT_TYPES = [
  "5xx",
  "429",
  "reject",
  "never_answer",
  "delay",
  "malformed_json",
  "schema_violation",
  "truncated",
] as const;
export type FaultType = (typeof FAULT_TYPES)[number];

export interface FaultIn {
  type: FaultType;
  model?: string | null;
  retry_after?: number | null;
  seconds?: number | null;
  status?: number | null;
}

export interface Fault extends FaultIn {
  id: number;
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.code) return `The server answered ${response.status} (${body.code}).`;
  } catch {
    // not JSON
  }
  return `The server answered ${response.status}.`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
  });
  if (!response.ok) throw new Error(await describeFailure(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const fetchPrompts = (signal?: AbortSignal) =>
  request<PromptVersion[]>("/api/prompts", { signal });

export const fetchSamples = (offset: number, limit: number, signal?: AbortSignal) =>
  request<Page<Sample>>(`/api/samples${query({ offset, limit })}`, { signal });

export const fetchRequests = (offset: number, limit: number, signal?: AbortSignal) =>
  request<Page<RequestSummary>>(`/api/requests${query({ offset, limit })}`, { signal });

export const fetchRequest = (requestId: string, signal?: AbortSignal) =>
  request<RequestDetail>(`/api/requests/${encodeURIComponent(requestId)}`, { signal });

export const fetchIdempotency = (offset: number, limit: number, signal?: AbortSignal) =>
  request<Page<IdempotencyRecord>>(`/api/idempotency-requests${query({ offset, limit })}`, { signal });

export const fetchCalls = (
  filters: { request_id?: string; status?: string; operation?: string },
  offset: number,
  limit: number,
  signal?: AbortSignal,
) => request<Page<LlmCall>>(`/api/llm-calls${query({ ...filters, offset, limit })}`, { signal });

export const fetchProvider = (signal?: AbortSignal) =>
  request<ProviderState>("/api/_provider", { signal });

export const switchProvider = (provider: ProviderName) =>
  request<ProviderState>("/api/_provider", { method: "PUT", body: JSON.stringify({ provider }) });

export const fetchFaults = (signal?: AbortSignal) => request<Fault[]>("/sim/_sim/faults", { signal });

export const addFault = (fault: FaultIn) =>
  request<Fault>("/sim/_sim/faults", { method: "POST", body: JSON.stringify(fault) });

export const removeFault = (id: number) =>
  request<void>(`/sim/_sim/faults/${id}`, { method: "DELETE" });

export const clearFaults = () => request<void>("/sim/_sim/faults", { method: "DELETE" });

/** POST /process, keeping every outcome: a record or a classified error. */
export async function processMessage(
  message: string,
  options: { idempotencyKey: string },
): Promise<ProcessOutcome> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
    "Idempotency-Key": options.idempotencyKey,
  };
  const response = await fetch("/api/process", {
    method: "POST",
    headers,
    body: JSON.stringify({ message }),
  });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const isError = !response.ok;
  return {
    status: response.status,
    requestId: response.headers.get("X-Request-ID"),
    replayed: response.headers.get("Idempotent-Replayed") === "true",
    retryAfter: response.headers.get("Retry-After"),
    ok: isError ? null : (body as ProcessOk),
    error: isError
      ? ((body as ApiErrorBody | null) ?? {
          code: "unreadable_response",
          message: "The server's answer could not be read.",
          retryable: true,
        })
      : null,
  };
}
