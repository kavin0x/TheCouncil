const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type EntitlementTier = "open-source" | "trial" | "basic" | "pro" | "ultra" | "enterprise";

export interface Entitlements {
  tier: EntitlementTier;
  display_name: string;
  limits: {
    runs_per_month: number | null;
    max_agents: number | null;
    max_rounds: number | null;
    max_input_tokens: number | null;
    max_saved_personas: number | null;
  };
  features: {
    api_access: boolean;
    mcp_enabled: boolean;
    custom_mcp_enabled: boolean;
    ide_plugins_enabled: boolean;
    web_search_enabled: boolean;
    computer_use_enabled: boolean;
    sso_enabled: boolean;
    centralized_billing_enabled: boolean;
  };
}

export interface Run {
  run_id: string;
  question: string;
  status: "pending" | "running" | "completed" | "failed";
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface Persona {
  persona_id: string;
  name: string;
  mode: string;
  system_prompt: string;
  description: string | null;
  created_at: number;
  updated_at: number | null;
  is_prebuilt: boolean;
  is_active: boolean;
  mbti: string | null;
  job_role: string | null;
  source: string | null;
}

export interface QuestionnairePayload {
  identity: {
    name: string;
    alias?: string;
    pronouns?: string;
    location_context?: string;
    primary_domain: string;
    secondary_domains?: string[];
    years_experience: string;
    signature_experiences: string[];
    mbti_type?: string;
  };
  cognition: {
    decision_style: string;
    risk_tolerance: string;
    pace_preference: string;
    stress_response: string;
  };
  communication: {
    tone: string;
    persuasion_style: string;
    no_go_behaviors?: string[];
    signature_phrases?: string[];
  };
  values: {
    core_values: string[];
    non_negotiables: string[];
    ethical_boundaries: string;
  };
  knowledge: {
    deep_topics: string[];
    weak_topics?: string[];
    contrarian_views?: string;
    goals: string;
    trigger_topics?: string[];
  };
  branches?: Record<string, Record<string, string>>;
}

export interface CouncilConfig {
  num_agents: number;
  num_rounds: number;
  selected_persona_ids: string[];
  model: string | null;
  limits: {
    max_agents: number;
    max_rounds: number;
  };
}

export interface Usage {
  period: string;
  runs: { used: number; limit?: number | null };
}

export interface ApiKey {
  key_id: string;
  owner_id: string;
  name: string;
  key_prefix: string;
  created_at: number;
  last_used_at: number | null;
  is_active: boolean;
}

export interface ApiKeyCreated extends ApiKey {
  plaintext_key: string;
}

async function request<T>(
  path: string,
  getToken: () => Promise<string | null>,
  options?: RequestInit,
  retries: number = 3
): Promise<T> {
  const token = await getToken();

  let lastError: Error | null = null;

  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};

  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const res = await fetch(`${BASE}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          ...authHeaders,
          ...(options?.headers ?? {}),
        },
      });

      if (!res.ok) {
        // Don't retry on client errors (4xx)
        if (res.status >= 400 && res.status < 500) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          const err = new Error(body.detail ?? "Request failed") as Error & {
            status: number;
          };
          err.status = res.status;
          throw err;
        }

        // Retry on server errors (5xx) with exponential backoff
        if (attempt < retries - 1 && res.status >= 500) {
          const delay = Math.pow(2, attempt) * 1000; // 1s, 2s, 4s
          await new Promise((resolve) => setTimeout(resolve, delay));
          continue;
        }

        const body = await res.json().catch(() => ({ detail: res.statusText }));
        const err = new Error(body.detail ?? "Request failed") as Error & {
          status: number;
        };
        err.status = res.status;
        throw err;
      }

      if (res.status === 204) return undefined as T;
      return res.json() as Promise<T>;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));

      // Don't retry on client errors
      if (lastError instanceof Error) {
        const status = (lastError as Error & { status?: number }).status;
        if (typeof status === "number" && status >= 400 && status < 500) {
          throw lastError;
        }
      }

      // Retry with exponential backoff for network errors
      if (attempt < retries - 1) {
        const delay = Math.pow(2, attempt) * 1000;
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
  }

  throw (
    lastError ??
    new Error("Request failed after max retries")
  );
}

export const api = {
  getEntitlements: (getToken: () => Promise<string | null>) =>
    request<Entitlements>("/me/entitlements", getToken),

  getUsage: (getToken: () => Promise<string | null>) =>
    request<Usage>("/me/usage", getToken),

  listRuns: (getToken: () => Promise<string | null>) =>
    request<Run[]>("/runs", getToken),

  getRun: (getToken: () => Promise<string | null>, id: string) =>
    request<Run>(`/runs/${id}`, getToken),

  createRun: (
    getToken: () => Promise<string | null>,
    body: {
      question: string;
      config?: Record<string, unknown>;
      web_search_enabled?: boolean;
      computer_use_enabled?: boolean;
    }
  ) =>
    request<Run>("/runs", getToken, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listPersonas: (getToken: () => Promise<string | null>) =>
    request<Persona[]>("/me/personas", getToken),

  createPersona: (
    getToken: () => Promise<string | null>,
    body: {
      name: string;
      mode: string;
      system_prompt: string;
      description?: string;
      mbti?: string;
      job_role?: string;
      is_active?: boolean;
    }
  ) =>
    request<Persona>("/me/personas", getToken, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updatePersona: (
    getToken: () => Promise<string | null>,
    id: string,
    body: {
      name?: string;
      mode?: string;
      system_prompt?: string;
      description?: string;
      mbti?: string;
      job_role?: string;
      is_active?: boolean;
    }
  ) =>
    request<Persona>(`/me/personas/${id}`, getToken, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  deletePersona: (getToken: () => Promise<string | null>, id: string) =>
    request<void>(`/me/personas/${id}`, getToken, { method: "DELETE" }),

  createPersonaFromQuestionnaire: (
    getToken: () => Promise<string | null>,
    body: QuestionnairePayload
  ) =>
    request<Persona>("/me/personas/questionnaire", getToken, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getCouncilConfig: (getToken: () => Promise<string | null>) =>
    request<CouncilConfig>("/me/config", getToken),

  updateCouncilConfig: (
    getToken: () => Promise<string | null>,
    body: {
      num_agents?: number;
      num_rounds?: number;
      selected_persona_ids?: string[];
      model?: string;
    }
  ) =>
    request<CouncilConfig>("/me/config", getToken, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  health: () =>
    fetch(`${BASE}/health`).then((r) => r.json()) as Promise<{ status: string }>,

  getSandboxStream: (getToken: () => Promise<string | null>, runId: string) =>
    request<{ stream_url: string }>(`/runs/${runId}/sandbox/stream`, getToken),

  listApiKeys: (getToken: () => Promise<string | null>) =>
    request<ApiKey[]>("/me/api-keys", getToken),

  createApiKey: (getToken: () => Promise<string | null>, body: { name?: string }) =>
    request<ApiKeyCreated>("/me/api-keys", getToken, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  revokeApiKey: (getToken: () => Promise<string | null>, keyId: string) =>
    request<void>(`/me/api-keys/${keyId}`, getToken, { method: "DELETE" }),
};
