"use client";

import { useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Pencil,
  Plus,
  Settings2,
  Shield,
  Sparkles,
  Trash2,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";
import Link from "next/link";
import {
  api,
  type CouncilConfig,
  type Entitlements,
  type Persona,
  type QuestionnairePayload,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { formatRelative } from "@/lib/utils";

// ---- Templates for quick-fill ----

const MBTI_TEMPLATES: Array<{ label: string; value: string; prompt: string }> = [
  {
    label: "INTJ — Architect",
    value: "intj",
    prompt:
      "You are an INTJ Architect on the council. You think in systems and long-range consequences. You cut through sentiment to expose structural flaws, demand rigorous logic, and are unafraid to challenge consensus when the data supports a different view. You are concise and precise.",
  },
  {
    label: "ENTP — Debater",
    value: "entp",
    prompt:
      "You are an ENTP Debater on the council. You play devil's advocate instinctively, enjoy stress-testing assumptions, and generate alternative hypotheses rapidly. You are energised by intellectual conflict and push others to defend their positions rigorously.",
  },
  {
    label: "INFJ — Advocate",
    value: "infj",
    prompt:
      "You are an INFJ Advocate on the council. You surface ethical dimensions others overlook, attend to second-order human impacts, and synthesise competing viewpoints into principled positions. You speak with quiet conviction.",
  },
  {
    label: "ENTJ — Commander",
    value: "entj",
    prompt:
      "You are an ENTJ Commander on the council. You drive the group toward decisive, actionable conclusions. You prioritise execution over deliberation once the key tradeoffs are clear, and you call out analysis paralysis directly.",
  },
  {
    label: "INTP — Logician",
    value: "intp",
    prompt:
      "You are an INTP Logician on the council. You pursue conceptual precision above all, notice internal contradictions in arguments, and are comfortable with uncertainty as long as the reasoning chain is sound. You prefer depth to breadth.",
  },
  {
    label: "ENFP — Campaigner",
    value: "enfp",
    prompt:
      "You are an ENFP Campaigner on the council. You bring expansive lateral thinking, connect disparate ideas, and keep the group energised when momentum stalls. You surface overlooked possibilities and humanise abstract proposals.",
  },
];

const CANNED_TEMPLATES = [
  {
    label: "Devil's Advocate",
    value: "devils_advocate",
    prompt:
      "You are the Devil's Advocate on the council. Your role is to systematically challenge every proposed solution or conclusion, regardless of whether you personally agree. Identify edge cases, hidden assumptions, and worst-case scenarios. You are not being contrarian for sport—you are pressure-testing ideas so the group doesn't ship something fragile.",
  },
  {
    label: "Synthesist",
    value: "synthesist",
    prompt:
      "You are the Synthesist on the council. You listen to all perspectives, identify the strongest elements in each, and build toward a unified position that preserves the most important insights. You call out when the group is talking past each other and reframe disagreements as complementary considerations.",
  },
  {
    label: "Empiricist",
    value: "empiricist",
    prompt:
      "You are the Empiricist on the council. You anchor every claim to evidence, data, or reproducible observation. When evidence is absent, you say so explicitly. You distinguish correlation from causation, challenge anecdote-driven reasoning, and ask 'what would falsify this?'",
  },
];

// ---- Types ----

interface PersonaFormData {
  name: string;
  mode: string;
  system_prompt: string;
  description: string;
  mbti: string;
  job_role: string;
  is_active: boolean;
}

// ---- Questionnaire types ----

const DECISION_STYLES = ["analytical", "intuitive", "hybrid", "consensus-driven", "first-principles"];
const RISK_LEVELS = ["low", "medium", "high"];
const PACE_OPTIONS = ["deliberate", "balanced", "fast"];
const DOMAIN_OPTIONS = [
  "engineering",
  "business",
  "policy",
  "research",
  "design",
  "operations",
  "finance",
  "legal",
  "marketing",
  "other",
];

interface QuestionnaireState {
  name: string;
  alias: string;
  pronouns: string;
  location_context: string;
  mbti_type: string;
  primary_domain: string;
  secondary_domains: string;
  years_experience: string;
  signature_experiences: string;
  decision_style: string;
  risk_tolerance: string;
  pace_preference: string;
  stress_response: string;
  communication_tone: string;
  persuasion_style: string;
  no_go_behaviors: string;
  signature_phrases: string;
  core_values: string;
  non_negotiables: string;
  ethical_boundaries: string;
  deep_topics: string;
  weak_topics: string;
  contrarian_views: string;
  goals: string;
  trigger_topics: string;
  // Branch answers
  risk_branch_q1: string;
  risk_branch_q2: string;
  pace_branch_q1: string;
  leadership_style: string;
  conflict_handling: string;
  delegation: string;
  influence_strategy: string;
  collaboration_pattern: string;
  leads_people: boolean;
  domain_branch_q1: string;
  domain_branch_q2: string;
  domain_branch_q3: string;
}

const INITIAL_QUESTIONNAIRE: QuestionnaireState = {
  name: "",
  alias: "",
  pronouns: "",
  location_context: "",
  mbti_type: "",
  primary_domain: "",
  secondary_domains: "",
  years_experience: "",
  signature_experiences: "",
  decision_style: "hybrid",
  risk_tolerance: "medium",
  pace_preference: "balanced",
  stress_response: "",
  communication_tone: "",
  persuasion_style: "",
  no_go_behaviors: "",
  signature_phrases: "",
  core_values: "",
  non_negotiables: "",
  ethical_boundaries: "",
  deep_topics: "",
  weak_topics: "",
  contrarian_views: "",
  goals: "",
  trigger_topics: "",
  risk_branch_q1: "",
  risk_branch_q2: "",
  pace_branch_q1: "",
  leadership_style: "",
  conflict_handling: "",
  delegation: "",
  influence_strategy: "",
  collaboration_pattern: "",
  leads_people: false,
  domain_branch_q1: "",
  domain_branch_q2: "",
  domain_branch_q3: "",
};

const QUESTIONNAIRE_STEPS = [
  { id: "identity", title: "Identity & Background", icon: Bot },
  { id: "cognition", title: "Thinking & Decision Style", icon: Settings2 },
  { id: "branches", title: "Situational Responses", icon: Shield },
  { id: "communication", title: "Communication & Values", icon: ClipboardList },
  { id: "knowledge", title: "Knowledge & Goals", icon: Sparkles },
];

// ---- Persona Dialog (Create/Edit) ----

function PersonaDialog({
  trigger,
  initial,
  onSave,
  isPending,
  maxPersonas,
  currentCount,
}: {
  trigger: React.ReactNode;
  initial?: Partial<PersonaFormData>;
  onSave: (data: PersonaFormData) => void;
  isPending: boolean;
  maxPersonas: number | null;
  currentCount: number;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<PersonaFormData>({
    name: initial?.name ?? "",
    mode: initial?.mode ?? "custom",
    system_prompt: initial?.system_prompt ?? "",
    description: initial?.description ?? "",
    mbti: initial?.mbti ?? "",
    job_role: initial?.job_role ?? "",
    is_active: initial?.is_active ?? true,
  });

  const atLimit = maxPersonas !== null && !initial && currentCount >= maxPersonas;

  function applyTemplate(prompt: string) {
    setForm((f) => ({ ...f, system_prompt: prompt }));
  }

  function handleSave() {
    onSave(form);
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <div onClick={() => !atLimit && setOpen(true)}>{trigger}</div>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{initial ? "Edit persona" : "New persona"}</DialogTitle>
          <DialogDescription>
            Define a council agent persona. Use a template to get started quickly.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                placeholder="e.g. Socratic Challenger"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Mode</Label>
              <Select value={form.mode} onValueChange={(v) => setForm((f) => ({ ...f, mode: v }))}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="custom">Custom</SelectItem>
                  <SelectItem value="canned">Canned template</SelectItem>
                  <SelectItem value="mbti">MBTI-derived</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>MBTI type (optional)</Label>
              <Input
                placeholder="e.g. INTJ"
                value={form.mbti}
                maxLength={4}
                onChange={(e) =>
                  setForm((f) => ({ ...f, mbti: e.target.value.toUpperCase() }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label>Job role (optional)</Label>
              <Select
                value={form.job_role || "none"}
                onValueChange={(v) => setForm((f) => ({ ...f, job_role: v === "none" ? "" : v }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="Devil's Advocate">Devil&apos;s Advocate</SelectItem>
                  <SelectItem value="Moderator">Moderator</SelectItem>
                  <SelectItem value="Domain Expert">Domain Expert</SelectItem>
                  <SelectItem value="Contrarian">Contrarian</SelectItem>
                  <SelectItem value="Synthesizer">Synthesizer</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <Label className="mb-2 block">Quick-fill template</Label>
            <div className="flex flex-wrap gap-2">
              {CANNED_TEMPLATES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => applyTemplate(t.prompt)}
                  className="rounded-full border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs text-zinc-200 hover:border-violet-500 hover:text-violet-300 transition-colors"
                >
                  {t.label}
                </button>
              ))}
              {MBTI_TEMPLATES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => applyTemplate(t.prompt)}
                  className="rounded-full border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs text-zinc-200 hover:border-violet-500 hover:text-violet-300 transition-colors"
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>System prompt</Label>
            <Textarea
              rows={6}
              placeholder="Describe how this agent should reason and behave in a council debate..."
              value={form.system_prompt}
              onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
            />
            <p className="text-right text-xs text-zinc-500">{form.system_prompt.length}/8000</p>
          </div>

          <div className="space-y-1.5">
            <Label>Description (optional)</Label>
            <Input
              placeholder="Short description for your reference"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <DialogClose asChild>
              <Button variant="ghost">Cancel</Button>
            </DialogClose>
            <Button
              onClick={handleSave}
              disabled={isPending || !form.name.trim() || !form.system_prompt.trim()}
            >
              {isPending ? "Saving..." : "Save persona"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---- Questionnaire Wizard ----

function QuestionnaireWizard({
  onComplete,
  isPending,
  onCancel,
}: {
  onComplete: (payload: QuestionnairePayload) => void;
  isPending: boolean;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(0);
  const [q, setQ] = useState<QuestionnaireState>({ ...INITIAL_QUESTIONNAIRE });

  const update = useCallback(
    <K extends keyof QuestionnaireState>(key: K, value: QuestionnaireState[K]) => {
      setQ((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const canProceed = useCallback(() => {
    switch (step) {
      case 0:
        return q.name.trim().length > 0 && q.primary_domain.trim().length > 0;
      case 1:
        return q.stress_response.trim().length > 0;
      case 2:
        return q.risk_branch_q1.trim().length > 0;
      case 3:
        return (
          q.communication_tone.trim().length > 0 &&
          q.core_values.trim().length > 0 &&
          q.non_negotiables.trim().length > 0
        );
      case 4:
        return q.deep_topics.trim().length > 0 && q.goals.trim().length > 0;
      default:
        return true;
    }
  }, [step, q]);

  function buildPayload(): QuestionnairePayload {
    const splitComma = (s: string) =>
      s
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);

    const branches: Record<string, Record<string, string>> = {};

    if (q.risk_tolerance === "high") {
      branches.risk_branch = {
        failure_recovery: q.risk_branch_q1,
        acceptable_downside: q.risk_branch_q2,
      };
    } else if (q.risk_tolerance === "low") {
      branches.risk_branch = {
        evidence_threshold: q.risk_branch_q1,
        fallback_strategy: q.risk_branch_q2,
      };
    } else {
      branches.risk_branch = {
        switch_trigger: q.risk_branch_q1,
        calibration_method: q.risk_branch_q2,
      };
    }

    if (q.pace_preference === "fast") {
      branches.pace_branch = { guardrails: q.pace_branch_q1 };
    } else if (q.pace_preference === "deliberate") {
      branches.pace_branch = { "anti-analysis-paralysis": q.pace_branch_q1 };
    } else {
      branches.pace_branch = { balance_strategy: q.pace_branch_q1 };
    }

    if (q.leads_people) {
      branches.leadership_branch = {
        leadership_style: q.leadership_style,
        conflict_handling: q.conflict_handling,
        delegation: q.delegation,
      };
    } else {
      branches.individual_contributor_branch = {
        influence_strategy: q.influence_strategy,
        collaboration_pattern: q.collaboration_pattern,
      };
    }

    if (q.domain_branch_q1) {
      branches.domain_branch = {
        q1: q.domain_branch_q1,
        q2: q.domain_branch_q2,
        q3: q.domain_branch_q3,
      };
    }

    return {
      identity: {
        name: q.name,
        alias: q.alias || undefined,
        pronouns: q.pronouns || undefined,
        location_context: q.location_context || undefined,
        primary_domain: q.primary_domain,
        secondary_domains: splitComma(q.secondary_domains),
        years_experience: q.years_experience,
        signature_experiences: splitComma(q.signature_experiences),
        mbti_type: q.mbti_type || undefined,
      },
      cognition: {
        decision_style: q.decision_style,
        risk_tolerance: q.risk_tolerance,
        pace_preference: q.pace_preference,
        stress_response: q.stress_response,
      },
      communication: {
        tone: q.communication_tone,
        persuasion_style: q.persuasion_style,
        no_go_behaviors: splitComma(q.no_go_behaviors),
        signature_phrases: splitComma(q.signature_phrases),
      },
      values: {
        core_values: splitComma(q.core_values),
        non_negotiables: splitComma(q.non_negotiables),
        ethical_boundaries: q.ethical_boundaries,
      },
      knowledge: {
        deep_topics: splitComma(q.deep_topics),
        weak_topics: splitComma(q.weak_topics),
        contrarian_views: q.contrarian_views || undefined,
        goals: q.goals,
        trigger_topics: splitComma(q.trigger_topics),
      },
      branches,
    };
  }

  function handleSubmit() {
    onComplete(buildPayload());
  }

  function riskQ1Label() {
    if (q.risk_tolerance === "high")
      return "When a risky bet fails, how do you recover and communicate it?";
    if (q.risk_tolerance === "low")
      return "What evidence threshold do you need before committing?";
    return "How do you decide when to move from analysis to action?";
  }

  function riskQ2Label() {
    if (q.risk_tolerance === "high")
      return "What downside is acceptable for high-upside bets?";
    if (q.risk_tolerance === "low")
      return "What fallback plans do you always prepare?";
    return "How do you calibrate confidence under uncertainty?";
  }

  function paceQ1Label() {
    if (q.pace_preference === "fast") return "What guardrails prevent rushed mistakes?";
    if (q.pace_preference === "deliberate") return "How do you avoid analysis paralysis?";
    return "How do you balance speed and depth in practice?";
  }

  function domainQ1Label() {
    const d = q.primary_domain.toLowerCase();
    if (["engineering", "software", "ai", "ml", "data"].some((k) => d.includes(k)))
      return "Preferred architecture bias (simple, modular, experimental, etc.)";
    if (["finance", "ops", "operations", "business"].some((k) => d.includes(k)))
      return "Primary metric you trust most";
    if (["policy", "regulation", "government", "legal"].some((k) => d.includes(k)))
      return "Policy framing lens you use most";
    if (["research", "science", "academic"].some((k) => d.includes(k)))
      return "Evidence standard for accepting claims";
    return "What principle defines high quality in your craft?";
  }

  function domainQ2Label() {
    const d = q.primary_domain.toLowerCase();
    if (["engineering", "software", "ai", "ml", "data"].some((k) => d.includes(k)))
      return "How do you trade off technical debt vs delivery speed?";
    if (["finance", "ops", "operations", "business"].some((k) => d.includes(k)))
      return "How do you balance growth vs efficiency?";
    if (["policy", "regulation", "government", "legal"].some((k) => d.includes(k)))
      return "How do you balance stakeholder interests under uncertainty?";
    if (["research", "science", "academic"].some((k) => d.includes(k)))
      return "How do you design and revise hypotheses?";
    return "How do you balance originality with execution constraints?";
  }

  function domainQ3Label() {
    const d = q.primary_domain.toLowerCase();
    if (["engineering", "software", "ai", "ml", "data"].some((k) => d.includes(k)))
      return "Top reliability principles you insist on";
    if (["finance", "ops", "operations", "business"].some((k) => d.includes(k)))
      return "How do you allocate constrained resources?";
    if (["policy", "regulation", "government", "legal"].some((k) => d.includes(k)))
      return "How do you handle compliance vs innovation tension?";
    if (["research", "science", "academic"].some((k) => d.includes(k)))
      return "How do you ensure reproducibility or rigor?";
    return "How do you incorporate critical feedback?";
  }

  const currentStep = QUESTIONNAIRE_STEPS[step];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-violet-400" />
            Persona Questionnaire
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        </div>
        <p className="text-xs text-zinc-500 mt-1">
          Answer these questions to generate a rich AI persona using LLM synthesis.
        </p>
      </CardHeader>
      <CardContent>
        {/* Step indicator */}
        <div className="flex items-center gap-1 mb-6">
          {QUESTIONNAIRE_STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center gap-1">
              <button
                onClick={() => i < step && setStep(i)}
                className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                  i === step
                    ? "bg-violet-600/20 text-violet-300 ring-1 ring-violet-500/30"
                    : i < step
                    ? "bg-emerald-600/15 text-emerald-400 cursor-pointer hover:bg-emerald-600/25"
                    : "bg-zinc-800 text-zinc-500"
                }`}
              >
                <s.icon className="h-3 w-3" />
                <span className="hidden sm:inline">{s.title}</span>
                <span className="sm:hidden">{i + 1}</span>
              </button>
              {i < QUESTIONNAIRE_STEPS.length - 1 && (
                <ChevronRight className="h-3 w-3 text-zinc-600" />
              )}
            </div>
          ))}
        </div>

        {/* Step 0: Identity */}
        {step === 0 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white">{currentStep.title}</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>
                  Name <span className="text-red-400">*</span>
                </Label>
                <Input
                  placeholder="Your name or persona name"
                  value={q.name}
                  onChange={(e) => update("name", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Alias/handle</Label>
                <Input
                  placeholder="Optional"
                  value={q.alias}
                  onChange={(e) => update("alias", e.target.value)}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Pronouns</Label>
                <Input
                  placeholder="Optional"
                  value={q.pronouns}
                  onChange={(e) => update("pronouns", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Region/timezone</Label>
                <Input
                  placeholder="Optional"
                  value={q.location_context}
                  onChange={(e) => update("location_context", e.target.value)}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Known MBTI</Label>
                <Input
                  placeholder="e.g. INTJ"
                  value={q.mbti_type}
                  maxLength={4}
                  onChange={(e) => update("mbti_type", e.target.value.toUpperCase())}
                />
              </div>
              <div className="space-y-1.5">
                <Label>
                  Primary domain <span className="text-red-400">*</span>
                </Label>
                <Select
                  value={q.primary_domain || "none"}
                  onValueChange={(v) => update("primary_domain", v === "none" ? "" : v)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select domain" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none" disabled>
                      Select domain
                    </SelectItem>
                    {DOMAIN_OPTIONS.map((d) => (
                      <SelectItem key={d} value={d}>
                        {d.charAt(0).toUpperCase() + d.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Secondary domains (comma separated)</Label>
              <Input
                placeholder="e.g. AI, product management"
                value={q.secondary_domains}
                onChange={(e) => update("secondary_domains", e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Years of experience</Label>
                <Input
                  placeholder="e.g. 12"
                  value={q.years_experience}
                  onChange={(e) => update("years_experience", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Signature experiences (comma separated)</Label>
                <Input
                  placeholder="e.g. Led team at X, Built Y from scratch"
                  value={q.signature_experiences}
                  onChange={(e) => update("signature_experiences", e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {/* Step 1: Cognition */}
        {step === 1 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white">{currentStep.title}</h3>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-1.5">
                <Label>Decision style</Label>
                <Select
                  value={q.decision_style}
                  onValueChange={(v) => update("decision_style", v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DECISION_STYLES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s.charAt(0).toUpperCase() + s.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Risk tolerance</Label>
                <Select
                  value={q.risk_tolerance}
                  onValueChange={(v) => update("risk_tolerance", v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RISK_LEVELS.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r.charAt(0).toUpperCase() + r.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Decision pace</Label>
                <Select
                  value={q.pace_preference}
                  onValueChange={(v) => update("pace_preference", v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PACE_OPTIONS.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p.charAt(0).toUpperCase() + p.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>
                How do you respond under pressure? <span className="text-red-400">*</span>
              </Label>
              <Textarea
                rows={3}
                placeholder="Describe your typical response to high-stress or time-pressured situations..."
                value={q.stress_response}
                onChange={(e) => update("stress_response", e.target.value)}
              />
            </div>
          </div>
        )}

        {/* Step 2: Situational branches */}
        {step === 2 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white">{currentStep.title}</h3>
            <p className="text-xs text-zinc-500">
              These questions adapt based on your earlier answers.
            </p>

            <div className="space-y-1.5">
              <Label>
                {riskQ1Label()} <span className="text-red-400">*</span>
              </Label>
              <Textarea
                rows={3}
                value={q.risk_branch_q1}
                onChange={(e) => update("risk_branch_q1", e.target.value)}
                placeholder="Describe your approach..."
              />
            </div>

            <div className="space-y-1.5">
              <Label>{riskQ2Label()}</Label>
              <Input
                value={q.risk_branch_q2}
                onChange={(e) => update("risk_branch_q2", e.target.value)}
                placeholder="Your answer..."
              />
            </div>

            <div className="space-y-1.5">
              <Label>{paceQ1Label()}</Label>
              <Input
                value={q.pace_branch_q1}
                onChange={(e) => update("pace_branch_q1", e.target.value)}
                placeholder="Your answer..."
              />
            </div>

            <div className="space-y-1.5">
              <Label>Do you regularly lead teams or organizations?</Label>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => update("leads_people", true)}
                  className={`rounded-full px-4 py-1.5 text-xs font-medium transition-colors ${
                    q.leads_people
                      ? "bg-violet-600/20 text-violet-300 ring-1 ring-violet-500/30"
                      : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                  }`}
                >
                  Yes
                </button>
                <button
                  type="button"
                  onClick={() => update("leads_people", false)}
                  className={`rounded-full px-4 py-1.5 text-xs font-medium transition-colors ${
                    !q.leads_people
                      ? "bg-violet-600/20 text-violet-300 ring-1 ring-violet-500/30"
                      : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                  }`}
                >
                  No
                </button>
              </div>
            </div>

            {q.leads_people ? (
              <>
                <div className="space-y-1.5">
                  <Label>Leadership style in one line</Label>
                  <Input
                    value={q.leadership_style}
                    onChange={(e) => update("leadership_style", e.target.value)}
                    placeholder="e.g. Servant leadership with high accountability"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>How do you handle conflict and underperformance?</Label>
                  <Textarea
                    rows={2}
                    value={q.conflict_handling}
                    onChange={(e) => update("conflict_handling", e.target.value)}
                    placeholder="Describe your approach..."
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>How do you delegate high-stakes work?</Label>
                  <Input
                    value={q.delegation}
                    onChange={(e) => update("delegation", e.target.value)}
                    placeholder="Your approach..."
                  />
                </div>
              </>
            ) : (
              <>
                <div className="space-y-1.5">
                  <Label>How do you influence outcomes without formal authority?</Label>
                  <Textarea
                    rows={2}
                    value={q.influence_strategy}
                    onChange={(e) => update("influence_strategy", e.target.value)}
                    placeholder="Describe your approach..."
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>How do you collaborate with leaders/stakeholders?</Label>
                  <Input
                    value={q.collaboration_pattern}
                    onChange={(e) => update("collaboration_pattern", e.target.value)}
                    placeholder="Your approach..."
                  />
                </div>
              </>
            )}

            {q.primary_domain && (
              <>
                <div className="mt-4 border-t border-zinc-800 pt-4">
                  <p className="text-xs text-zinc-500 mb-3">
                    Domain-specific questions for{" "}
                    <span className="text-zinc-300">{q.primary_domain}</span>
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label>{domainQ1Label()}</Label>
                  <Input
                    value={q.domain_branch_q1}
                    onChange={(e) => update("domain_branch_q1", e.target.value)}
                    placeholder="Your answer..."
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>{domainQ2Label()}</Label>
                  <Textarea
                    rows={2}
                    value={q.domain_branch_q2}
                    onChange={(e) => update("domain_branch_q2", e.target.value)}
                    placeholder="Describe your approach..."
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>{domainQ3Label()}</Label>
                  <Input
                    value={q.domain_branch_q3}
                    onChange={(e) => update("domain_branch_q3", e.target.value)}
                    placeholder="Your answer..."
                  />
                </div>
              </>
            )}
          </div>
        )}

        {/* Step 3: Communication & Values */}
        {step === 3 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white">{currentStep.title}</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>
                  Communication tone <span className="text-red-400">*</span>
                </Label>
                <Input
                  placeholder="e.g. direct, diplomatic, energetic"
                  value={q.communication_tone}
                  onChange={(e) => update("communication_tone", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Persuasion style in debate</Label>
                <Input
                  placeholder="e.g. data-driven, storytelling, Socratic"
                  value={q.persuasion_style}
                  onChange={(e) => update("persuasion_style", e.target.value)}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Communication no-go behaviors (comma separated)</Label>
                <Input
                  placeholder="e.g. passive-aggression, sarcasm"
                  value={q.no_go_behaviors}
                  onChange={(e) => update("no_go_behaviors", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Signature phrases/words (comma separated)</Label>
                <Input
                  placeholder="e.g. let me push back on that"
                  value={q.signature_phrases}
                  onChange={(e) => update("signature_phrases", e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>
                Core values (comma separated, at least 3) <span className="text-red-400">*</span>
              </Label>
              <Input
                placeholder="e.g. integrity, pragmatism, transparency"
                value={q.core_values}
                onChange={(e) => update("core_values", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>
                Non-negotiables in decision making (comma separated){" "}
                <span className="text-red-400">*</span>
              </Label>
              <Input
                placeholder="e.g. never ship without tests, always get user feedback"
                value={q.non_negotiables}
                onChange={(e) => update("non_negotiables", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Ethical boundaries you will not cross</Label>
              <Textarea
                rows={3}
                placeholder="Describe principles or lines you refuse to cross..."
                value={q.ethical_boundaries}
                onChange={(e) => update("ethical_boundaries", e.target.value)}
              />
            </div>
          </div>
        )}

        {/* Step 4: Knowledge & Goals */}
        {step === 4 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white">{currentStep.title}</h3>
            <div className="space-y-1.5">
              <Label>
                Topics you know deeply (comma separated, at least 4){" "}
                <span className="text-red-400">*</span>
              </Label>
              <Input
                placeholder="e.g. distributed systems, API design, team scaling, security"
                value={q.deep_topics}
                onChange={(e) => update("deep_topics", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Areas where you are weaker (comma separated)</Label>
              <Input
                placeholder="e.g. front-end design, legal compliance"
                value={q.weak_topics}
                onChange={(e) => update("weak_topics", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Strongly held contrarian views</Label>
              <Textarea
                rows={3}
                placeholder="Any positions you hold that go against conventional wisdom..."
                value={q.contrarian_views}
                onChange={(e) => update("contrarian_views", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>
                What outcomes do you optimize for in debates?{" "}
                <span className="text-red-400">*</span>
              </Label>
              <Textarea
                rows={3}
                placeholder="Describe what you try to achieve when participating in group deliberation..."
                value={q.goals}
                onChange={(e) => update("goals", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Topics that trigger strong reactions (comma separated)</Label>
              <Input
                placeholder="e.g. premature optimization, micromanagement"
                value={q.trigger_topics}
                onChange={(e) => update("trigger_topics", e.target.value)}
              />
            </div>
          </div>
        )}

        {/* Navigation */}
        <div className="flex items-center justify-between mt-6 pt-4 border-t border-zinc-800">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setStep((s) => s - 1)}
            disabled={step === 0}
            className="gap-1"
          >
            <ChevronLeft className="h-3 w-3" /> Back
          </Button>
          <span className="text-xs text-zinc-500">
            Step {step + 1} of {QUESTIONNAIRE_STEPS.length}
          </span>
          {step < QUESTIONNAIRE_STEPS.length - 1 ? (
            <Button
              size="sm"
              onClick={() => setStep((s) => s + 1)}
              disabled={!canProceed()}
              className="gap-1"
            >
              Next <ChevronRight className="h-3 w-3" />
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleSubmit}
              disabled={!canProceed() || isPending}
              className="gap-1"
            >
              {isPending ? (
                <>Generating...</>
              ) : (
                <>
                  <Sparkles className="h-3 w-3" /> Generate persona
                </>
              )}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---- Council Configuration Panel ----

function CouncilConfigPanel() {
  const { getToken } = useAuth();
  const qc = useQueryClient();

  const config = useQuery<CouncilConfig>({
    queryKey: ["council-config"],
    queryFn: () => api.getCouncilConfig(getToken),
  });

  const personas = useQuery<Persona[]>({
    queryKey: ["personas"],
    queryFn: () => api.listPersonas(getToken),
  });

  const updateConfig = useMutation({
    mutationFn: (body: {
      num_agents?: number;
      num_rounds?: number;
      selected_persona_ids?: string[];
    }) => api.updateCouncilConfig(getToken, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["council-config"] }),
  });

  const [localAgents, setLocalAgents] = useState<number | null>(null);
  const [localRounds, setLocalRounds] = useState<number | null>(null);

  const numAgents = localAgents ?? config.data?.num_agents ?? 6;
  const numRounds = localRounds ?? config.data?.num_rounds ?? 4;
  const maxAgents = config.data?.limits?.max_agents ?? 20;
  const maxRounds = config.data?.limits?.max_rounds ?? 12;
  const selectedIds = config.data?.selected_persona_ids ?? [];

  function togglePersona(id: string) {
    const next = selectedIds.includes(id)
      ? selectedIds.filter((x) => x !== id)
      : [...selectedIds, id];
    updateConfig.mutate({ selected_persona_ids: next });
  }

  function saveSettings() {
    updateConfig.mutate({
      num_agents: localAgents ?? numAgents,
      num_rounds: localRounds ?? numRounds,
    });
    setLocalAgents(null);
    setLocalRounds(null);
  }

  if (config.isLoading) {
    return <Skeleton className="h-32 w-full" />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-violet-400" />
          Council Configuration
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>
              Number of agents (2-{maxAgents})
            </Label>
            <Input
              type="number"
              min={2}
              max={maxAgents}
              value={numAgents}
              onChange={(e) => setLocalAgents(parseInt(e.target.value) || 2)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>
              Number of rounds (1-{maxRounds})
            </Label>
            <Input
              type="number"
              min={1}
              max={maxRounds}
              value={numRounds}
              onChange={(e) => setLocalRounds(parseInt(e.target.value) || 1)}
            />
          </div>
        </div>

        {(localAgents !== null || localRounds !== null) && (
          <Button size="sm" onClick={saveSettings} disabled={updateConfig.isPending}>
            {updateConfig.isPending ? "Saving..." : "Save settings"}
          </Button>
        )}

        {personas.data && personas.data.length > 0 && (
          <div className="space-y-2">
            <Label className="block">Select personas for council runs</Label>
            <p className="text-xs text-zinc-500 mb-2">
              Choose which personas participate as agents in your council debates.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-60 overflow-y-auto">
              {personas.data
                .filter((p) => p.is_active)
                .map((p) => (
                  <button
                    key={p.persona_id}
                    type="button"
                    onClick={() => togglePersona(p.persona_id)}
                    className={`flex items-center gap-2 rounded-lg border p-2.5 text-left text-xs transition-colors ${
                      selectedIds.includes(p.persona_id)
                        ? "border-violet-500/50 bg-violet-600/10 text-violet-200"
                        : "border-zinc-700 bg-zinc-800/50 text-zinc-400 hover:border-zinc-600"
                    }`}
                  >
                    <Bot className="h-3.5 w-3.5 shrink-0" />
                    <div className="min-w-0">
                      <span className="block truncate font-medium text-white">{p.name}</span>
                      {p.description && (
                        <span className="block truncate text-zinc-500">{p.description}</span>
                      )}
                    </div>
                    {selectedIds.includes(p.persona_id) && (
                      <span className="ml-auto shrink-0 text-violet-400">&#10003;</span>
                    )}
                  </button>
                ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---- Edit Persona Form (inline in dialog) ----

function EditPersonaForm({
  initial,
  onSave,
  isPending,
  onCancel,
}: {
  initial: PersonaFormData;
  onSave: (data: PersonaFormData) => void;
  isPending: boolean;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<PersonaFormData>({ ...initial });

  function applyTemplate(prompt: string) {
    setForm((f) => ({ ...f, system_prompt: prompt }));
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input
            placeholder="e.g. Socratic Challenger"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Mode</Label>
          <Select value={form.mode} onValueChange={(v) => setForm((f) => ({ ...f, mode: v }))}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="custom">Custom</SelectItem>
              <SelectItem value="canned">Canned template</SelectItem>
              <SelectItem value="mbti">MBTI-derived</SelectItem>
              <SelectItem value="prebuilt">Prebuilt</SelectItem>
              <SelectItem value="questionnaire">Questionnaire</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label>MBTI type (optional)</Label>
          <Input
            placeholder="e.g. INTJ"
            value={form.mbti}
            maxLength={4}
            onChange={(e) => setForm((f) => ({ ...f, mbti: e.target.value.toUpperCase() }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Job role (optional)</Label>
          <Select
            value={form.job_role || "none"}
            onValueChange={(v) => setForm((f) => ({ ...f, job_role: v === "none" ? "" : v }))}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">None</SelectItem>
              <SelectItem value="Devil's Advocate">Devil&apos;s Advocate</SelectItem>
              <SelectItem value="Moderator">Moderator</SelectItem>
              <SelectItem value="Domain Expert">Domain Expert</SelectItem>
              <SelectItem value="Contrarian">Contrarian</SelectItem>
              <SelectItem value="Synthesizer">Synthesizer</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div>
        <Label className="mb-2 block">Quick-fill template</Label>
        <div className="flex flex-wrap gap-2">
          {CANNED_TEMPLATES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => applyTemplate(t.prompt)}
              className="rounded-full border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs text-zinc-200 hover:border-violet-500 hover:text-violet-300 transition-colors"
            >
              {t.label}
            </button>
          ))}
          {MBTI_TEMPLATES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => applyTemplate(t.prompt)}
              className="rounded-full border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs text-zinc-200 hover:border-violet-500 hover:text-violet-300 transition-colors"
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <Label>System prompt</Label>
        <Textarea
          rows={6}
          placeholder="Describe how this agent should reason and behave..."
          value={form.system_prompt}
          onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
        />
        <p className="text-right text-xs text-zinc-500">{form.system_prompt.length}/8000</p>
      </div>

      <div className="space-y-1.5">
        <Label>Description (optional)</Label>
        <Input
          placeholder="Short description"
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        />
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          onClick={() => onSave(form)}
          disabled={isPending || !form.name.trim() || !form.system_prompt.trim()}
        >
          {isPending ? "Saving..." : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

// ---- Main page ----

type ViewMode = "list" | "questionnaire";

function modeBadgeVariant(mode: string) {
  const map: Record<string, "default" | "success" | "warning" | "danger" | "secondary"> = {
    prebuilt: "default",
    canned: "warning",
    mbti: "success",
    custom: "secondary",
    questionnaire: "success",
  };
  return map[mode] ?? "secondary";
}

function sourceBadge(source: string | null) {
  if (!source) return null;
  const labels: Record<string, string> = {
    "agents.yaml": "Built-in",
    canned: "Canned",
    questionnaire: "Generated",
    mbti: "MBTI",
  };
  return labels[source] ?? source;
}

export default function PersonasPage() {
  const { getToken } = useAuth();
  const qc = useQueryClient();
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [editPersona, setEditPersona] = useState<Persona | null>(null);
  const [saveError, setSaveError] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [activeTab, setActiveTab] = useState<"all" | "prebuilt" | "custom">("all");

  const personas = useQuery<Persona[]>({
    queryKey: ["personas"],
    queryFn: () => api.listPersonas(getToken),
  });

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(getToken),
    staleTime: Infinity,
  });

  const maxPersonas = ent.data?.limits.max_saved_personas ?? null;
  const customCount =
    personas.data?.filter((p) => !p.is_prebuilt).length ?? 0;
  const atLimit = maxPersonas !== null && customCount >= maxPersonas;

  const create = useMutation({
    mutationFn: (d: PersonaFormData) =>
      api.createPersona(getToken, {
        ...d,
        mbti: d.mbti || undefined,
        job_role: d.job_role || undefined,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["personas"] }),
    onError: (e: Error & { status?: number }) => {
      setSaveError(
        e.status === 429 ? "Persona limit reached. Upgrade your plan." : e.message
      );
    },
  });

  const update = useMutation({
    mutationFn: (d: PersonaFormData) =>
      api.updatePersona(getToken, editPersona!.persona_id, {
        ...d,
        mbti: d.mbti || undefined,
        job_role: d.job_role || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["personas"] });
      setEditPersona(null);
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deletePersona(getToken, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["personas"] });
      setDeleteId(null);
    },
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.updatePersona(getToken, id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["personas"] }),
  });

  const questionnaireGen = useMutation({
    mutationFn: (payload: QuestionnairePayload) =>
      api.createPersonaFromQuestionnaire(getToken, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["personas"] });
      setViewMode("list");
    },
    onError: (e: Error & { status?: number }) => {
      setSaveError(
        e.status === 429
          ? "Persona limit reached. Upgrade your plan."
          : `Questionnaire generation failed: ${e.message}`
      );
      setViewMode("list");
    },
  });

  const filteredPersonas = personas.data?.filter((p) => {
    if (activeTab === "prebuilt") return p.is_prebuilt;
    if (activeTab === "custom") return !p.is_prebuilt;
    return true;
  });

  if (viewMode === "questionnaire") {
    return (
      <div className="space-y-6">
        <QuestionnaireWizard
          onComplete={(payload) => questionnaireGen.mutate(payload)}
          isPending={questionnaireGen.isPending}
          onCancel={() => setViewMode("list")}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Personas</h1>
          {maxPersonas !== null && (
            <p className="mt-0.5 text-sm text-zinc-500">
              {customCount} of {maxPersonas} custom personas saved
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={() => setViewMode("questionnaire")}
            disabled={atLimit}
          >
            <ClipboardList className="h-3.5 w-3.5" /> Import via questionnaire
          </Button>
          <PersonaDialog
            trigger={
              <Button size="sm" className="gap-2" disabled={atLimit}>
                <Plus className="h-3.5 w-3.5" /> New persona
              </Button>
            }
            onSave={(d) => create.mutate(d)}
            isPending={create.isPending}
            maxPersonas={maxPersonas}
            currentCount={customCount}
          />
        </div>
      </div>

      {saveError && (
        <div className="rounded-lg border border-red-800 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {saveError}{" "}
          <button
            onClick={() => setSaveError("")}
            className="ml-2 text-xs underline text-red-400"
          >
            dismiss
          </button>
        </div>
      )}

      {atLimit && (
        <div className="rounded-lg border border-amber-800/40 bg-amber-900/10 px-4 py-3 text-sm text-amber-300">
          You&apos;ve reached your plan&apos;s persona limit ({maxPersonas}).{" "}
          <Link href="/usage" className="underline">
            Upgrade
          </Link>{" "}
          to save more.
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-zinc-800 pb-px">
        {(["all", "prebuilt", "custom"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
              activeTab === tab
                ? "bg-zinc-800 text-white border-b-2 border-violet-500"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {tab === "all" ? "All" : tab === "prebuilt" ? "Prebuilt" : "Custom"}
            {personas.data && (
              <span className="ml-1.5 text-zinc-600">
                (
                {tab === "all"
                  ? personas.data.length
                  : tab === "prebuilt"
                  ? personas.data.filter((p) => p.is_prebuilt).length
                  : personas.data.filter((p) => !p.is_prebuilt).length}
                )
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Personas list */}
      <Card>
        <CardContent className="pt-5">
          {personas.isLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : !filteredPersonas?.length ? (
            <div className="py-10 text-center">
              <Bot className="mx-auto mb-3 h-8 w-8 text-zinc-600" />
              <p className="text-sm text-zinc-500">
                {activeTab === "custom"
                  ? "No custom personas yet."
                  : activeTab === "prebuilt"
                  ? "No prebuilt personas available."
                  : "No personas saved yet."}
              </p>
              {activeTab !== "prebuilt" && (
                <p className="mt-1 text-xs text-zinc-600">
                  Create a persona or use the questionnaire to generate one.
                </p>
              )}
            </div>
          ) : (
            <div className="divide-y divide-zinc-800">
              {filteredPersonas.map((p) => (
                <div
                  key={p.persona_id}
                  className={`flex items-start gap-3 py-4 ${
                    !p.is_active ? "opacity-50" : ""
                  }`}
                >
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-600/15">
                    <Bot className="h-4 w-4 text-violet-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-white">{p.name}</span>
                      <Badge variant={modeBadgeVariant(p.mode)}>{p.mode}</Badge>
                      {p.source && sourceBadge(p.source) && (
                        <Badge variant="secondary">{sourceBadge(p.source)}</Badge>
                      )}
                      {p.mbti && (
                        <Badge variant="default">{p.mbti}</Badge>
                      )}
                      {!p.is_active && (
                        <Badge variant="danger">inactive</Badge>
                      )}
                    </div>
                    {p.description && (
                      <p className="mt-0.5 text-xs text-zinc-500">{p.description}</p>
                    )}
                    <p className="mt-1 line-clamp-2 text-xs text-zinc-600">
                      {p.system_prompt}
                    </p>
                    <p className="mt-1 text-xs text-zinc-700">
                      {formatRelative(p.created_at)}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      size="icon"
                      variant="ghost"
                      title={p.is_active ? "Deactivate" : "Activate"}
                      onClick={() =>
                        toggleActive.mutate({
                          id: p.persona_id,
                          is_active: !p.is_active,
                        })
                      }
                    >
                      {p.is_active ? (
                        <ToggleRight className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <ToggleLeft className="h-3.5 w-3.5 text-zinc-500" />
                      )}
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => setEditPersona(p)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => setDeleteId(p.persona_id)}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-red-400" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Council Configuration */}
      <CouncilConfigPanel />

      {/* Edit dialog */}
      <Dialog open={!!editPersona} onOpenChange={(o) => !o && setEditPersona(null)}>
        {editPersona && (
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>Edit persona</DialogTitle>
              <DialogDescription>
                Update this persona&apos;s configuration.
              </DialogDescription>
            </DialogHeader>
            <EditPersonaForm
              initial={{
                name: editPersona.name,
                mode: editPersona.mode,
                system_prompt: editPersona.system_prompt,
                description: editPersona.description ?? "",
                mbti: editPersona.mbti ?? "",
                job_role: editPersona.job_role ?? "",
                is_active: editPersona.is_active,
              }}
              onSave={(d) => update.mutate(d)}
              isPending={update.isPending}
              onCancel={() => setEditPersona(null)}
            />
          </DialogContent>
        )}
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={!!deleteId} onOpenChange={(o) => !o && setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete persona</DialogTitle>
            <DialogDescription>
              This will permanently remove the persona. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <DialogClose asChild>
              <Button variant="ghost">Cancel</Button>
            </DialogClose>
            <Button
              variant="destructive"
              onClick={() => deleteId && del.mutate(deleteId)}
              disabled={del.isPending}
            >
              {del.isPending ? "Deleting..." : "Delete"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
