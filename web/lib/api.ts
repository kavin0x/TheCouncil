const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type TierName = "trial" | "basic" | "pro" | "ultra" | "enterprise";

export interface Entitlements {
  tier: TierName;
  display_name: string;
  limits: {
    runs_per_month: number;
    max_agents: number;
    max_rounds: number;
    max_input_tokens: number;
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
  runs: { used: number; limit: number };
}

export interface Billing {
  tier: TierName;
  display_name: string;
  price_usd_monthly: number;
  status: string;
  trial_end: number | null;
  next_renewal: number | null;
  stripe_customer_id: string | null;
}

async function request<T>(
  path: string,
  token: string,
  options?: RequestInit,
  retries: number = 3
): Promise<T> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const res = await fetch(`${BASE}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Requested-With": "XMLHttpRequest", // CSRF protection
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
  getEntitlements: (token: string) =>
    request<Entitlements>("/me/entitlements", token),

  getUsage: (token: string) => request<Usage>("/me/usage", token),

  getBilling: (token: string) => request<Billing>("/me/billing", token),

  createCheckout: (
    token: string,
    body: { tier: string; success_url: string; cancel_url: string }
  ) =>
    request<{ url: string }>("/me/billing/checkout", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  createPortal: (token: string, return_url: string) =>
    request<{ url: string }>("/me/billing/portal", token, {
      method: "POST",
      body: JSON.stringify({ return_url }),
    }),

  listRuns: (token: string) => request<Run[]>("/runs", token),

  getRun: (token: string, id: string) =>
    request<Run>(`/runs/${id}`, token),

  createRun: (
    token: string,
    body: {
      question: string;
      config?: Record<string, unknown>;
      web_search_enabled?: boolean;
      computer_use_enabled?: boolean;
    }
  ) =>
    request<Run>("/runs", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listPersonas: (token: string) =>
    request<Persona[]>("/me/personas", token),

  createPersona: (
    token: string,
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
    request<Persona>("/me/personas", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updatePersona: (
    token: string,
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
    request<Persona>(`/me/personas/${id}`, token, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  deletePersona: (token: string, id: string) =>
    request<void>(`/me/personas/${id}`, token, { method: "DELETE" }),

  createPersonaFromQuestionnaire: (
    token: string,
    body: QuestionnairePayload
  ) =>
    request<Persona>("/me/personas/questionnaire", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getCouncilConfig: (token: string) =>
    request<CouncilConfig>("/me/config", token),

  updateCouncilConfig: (
    token: string,
    body: {
      num_agents?: number;
      num_rounds?: number;
      selected_persona_ids?: string[];
      model?: string;
    }
  ) =>
    request<CouncilConfig>("/me/config", token, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  health: () =>
    fetch(`${BASE}/health`).then((r) => r.json()) as Promise<{ status: string }>,

  getSandboxStream: (token: string, runId: string) =>
    request<{ stream_url: string }>(`/runs/${runId}/sandbox/stream`, token),
};
