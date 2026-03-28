"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { api, type Entitlements, type Persona } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Badge,
  Button,
  Card,
  CardContent,
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

interface PersonaFormData {
  name: string;
  mode: string;
  system_prompt: string;
  description: string;
}

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

          {/* Template picker */}
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
              placeholder="Describe how this agent should reason and behave in a council debate…"
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
              {isPending ? "Saving…" : "Save persona"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function PersonasPage() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [editPersona, setEditPersona] = useState<Persona | null>(null);
  const [saveError, setSaveError] = useState("");

  const personas = useQuery<Persona[]>({
    queryKey: ["personas"],
    queryFn: () => api.listPersonas(token!),
  });

  const ent = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
    staleTime: Infinity,
  });

  const maxPersonas = ent.data?.limits.max_saved_personas ?? null;
  const currentCount = personas.data?.length ?? 0;
  const atLimit = maxPersonas !== null && currentCount >= maxPersonas;

  const create = useMutation({
    mutationFn: (d: PersonaFormData) => api.createPersona(token!, d),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["personas"] }),
    onError: (e: Error & { status?: number }) => {
      setSaveError(e.status === 429 ? "Persona limit reached. Upgrade your plan." : e.message);
    },
  });

  const update = useMutation({
    mutationFn: (d: PersonaFormData) => api.updatePersona(token!, editPersona!.persona_id, d),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["personas"] });
      setEditPersona(null);
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deletePersona(token!, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["personas"] });
      setDeleteId(null);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Personas</h1>
          {maxPersonas !== null && (
            <p className="mt-0.5 text-sm text-zinc-500">
              {currentCount} of {maxPersonas} saved
            </p>
          )}
        </div>
        <PersonaDialog
          trigger={
            <Button size="sm" className="gap-2" disabled={atLimit}>
              <Plus className="h-3.5 w-3.5" /> New persona
            </Button>
          }
          onSave={(d) => create.mutate(d)}
          isPending={create.isPending}
          maxPersonas={maxPersonas}
          currentCount={currentCount}
        />
      </div>

      {saveError && (
        <div className="rounded-lg border border-red-800 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {saveError}
          {" "}
          <Link href="/usage" className="underline">Upgrade plan</Link>
        </div>
      )}

      {atLimit && (
        <div className="rounded-lg border border-amber-800/40 bg-amber-900/10 px-4 py-3 text-sm text-amber-300">
          You&apos;ve reached your plan&apos;s persona limit ({maxPersonas}).{" "}
          <Link href="/usage" className="underline">Upgrade</Link> to save more.
        </div>
      )}

      <Card>
        <CardContent className="pt-5">
          {personas.isLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : personas.data?.length === 0 ? (
            <div className="py-10 text-center">
              <Bot className="mx-auto mb-3 h-8 w-8 text-zinc-600" />
              <p className="text-sm text-zinc-500">No personas saved yet.</p>
              <p className="mt-1 text-xs text-zinc-600">
                Create a persona to reuse as a council agent across runs.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-zinc-800">
              {personas.data?.map((p) => (
                <div key={p.persona_id} className="flex items-start gap-3 py-4">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-600/15">
                    <Bot className="h-4 w-4 text-violet-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">{p.name}</span>
                      <Badge variant="secondary">{p.mode}</Badge>
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

      {/* Edit dialog */}
      {editPersona && (
        <PersonaDialog
          trigger={<span />}
          initial={{ ...editPersona, description: editPersona.description ?? "" }}
          onSave={(d) => update.mutate(d)}
          isPending={update.isPending}
          maxPersonas={maxPersonas}
          currentCount={currentCount}
        />
      )}

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
              {del.isPending ? "Deleting…" : "Delete"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
