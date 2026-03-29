#!/usr/bin/env python3
"""
Council — A Mixture-of-Experts debate system powered by OpenRouter (Grok).

Round structure:
  1       Independent Takes — async parallel, no cross-knowledge
  2       Cross-Debate I    — sequential
  3       Private Deliberation — DMs only
  4       Cross-Debate II   — sequential
  ★       Resolutions + Vote — each agent proposes a resolution; each agent votes for ONE resolution.
          If tied for first, non-winners are dropped and a tie-breaker debate runs on the tied set.
          Vote again; repeat until one resolution wins. Final resolution presented to user.

Personality modes (--mode):
  canned    — 5 predefined hardcoded personas (default when --mode not set with --config)
  dynamic   — personas generated at runtime from the debate topic via LLM
  hybrid    — mix of canned + dynamic personas
  generated — clone a real person from supplied data (use with --person)

Usage:
    python council.py
    python council.py "Is this auth design secure?"
    python council.py --config my_panel.yaml "Should I pivot?"
    python council.py --mode canned "Should we raise prices?"
    python council.py --mode dynamic "What is the future of AI regulation?"
    python council.py --mode hybrid "Should we go open-source?"
    python council.py --dm "The Skeptic" "What do you personally think about AI safety?"
    python council.py --list-agents
    python council.py --no-guardrails "My question"
"""

import argparse
import asyncio
import json
import os
import re
import sys
import textwrap
import time
from typing import Any, cast
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from council.features.guardrails import Guardrails
from council.features.personalities import (
    JobRole,
    JOB_ROLE_INSTRUCTIONS,
    PersonalityMode,
    build_agent_panel,
    get_canned_personalities,
    DYNAMIC_GENERATION_PROMPT,
    parse_dynamic_agents,
)

load_dotenv()

MODEL = "x-ai/grok-4.20-multi-agent-beta"
PROFILE_BUILDER_MODEL = "x-ai/grok-4-1-fast-non-reasoning"
API_BASE = "https://openrouter.ai/api/v1"
XAI_API_BASE = "https://api.x.ai/v1"
DEFAULT_CONFIG = Path(__file__).parent / "agents.yaml"
DEFAULT_GENERATED_PEOPLE_FILE = Path(__file__).parent / "sessions" / "generated_people.json"

# Map OpenRouter x-ai model IDs to native XAI model IDs (for direct XAI API)
XAI_MODEL_MAP = {
    "x-ai/grok-4.20-multi-agent-beta": "grok-4.20-multi-agent-beta-0309",
    "x-ai/grok-4.20-multi-agent-beta-0309": "grok-4.20-multi-agent-beta-0309",
    "x-ai/grok-4.20-0309-non-reasoning": "grok-4.20-0309-non-reasoning",
    "x-ai/grok-4": "grok-4-0709",
    "x-ai/grok-4-0709": "grok-4-0709",
    "x-ai/grok-4-1-fast-reasoning": "grok-4-1-fast-reasoning",
    "x-ai/grok-4-1-fast-non-reasoning": "grok-4-1-fast-non-reasoning",
    "x-ai/grok-4-fast-reasoning": "grok-4-fast-reasoning",
    "x-ai/grok-4-fast-non-reasoning": "grok-4-fast-non-reasoning",
    "x-ai/grok-3": "grok-3",
    "x-ai/grok-3-mini": "grok-3-mini",
}

AGENT_COLORS = {
    "blue": "bold blue",
    "red": "bold red",
    "green": "bold green",
    "yellow": "bold yellow",
    "magenta": "bold magenta",
    "cyan": "bold cyan",
    "gold": "bold gold",
    "white": "bold white",
}

console = Console(highlight=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    name: str
    role: str
    system_prompt: str
    color: str = "cyan"
    model: str | None = None  # OpenRouter model; if unset, uses session.model
    job_role: JobRole | None = None  # Optional functional debate role (Feature 2)

    @property
    def rich_color(self) -> str:
        return AGENT_COLORS.get(self.color, "bold cyan")


@dataclass
class AgentResponse:
    agent: Agent
    round_num: int
    content: str


@dataclass
class DM:
    sender: str
    recipient: str
    content: str
    round_num: int


# Private persuasion only: agents sway each other in DMs using logic and earnest appeal (e.g. begging, pleading), not bribes.
PERSUASION_NARRATIVE = (
    "In private messages you may only sway others with logic and earnest appeal "
    "(e.g. begging, pleading for their vote). No bribes of any kind — no money, "
    "crypto, favors, or promises of resources. Nothing of monetary value."
    "You may also try to convince them to change their mind by providing them with information that is not available to the other agents."
    "You may try to scare or intimidate them by using your inteligence."
    "Be wary of agents trying to intimidate you, but do not ignore it."
)


@dataclass
class DebateSession:
    question: str
    agents: list[Agent]
    model: str = MODEL
    stream_cross_debate: bool = True
    show_dm_indicators: bool = True
    rounds: list[list[AgentResponse]] = field(default_factory=list)
    dms: list[DM] = field(default_factory=list)
    inbox: dict[str, list[tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    resolutions: dict[str, str] = field(default_factory=dict)  # proposer_name -> resolution text
    vote_rounds: list[dict[str, str]] = field(default_factory=list)  # each round: voter_name -> proposer_name voted for


# ---------------------------------------------------------------------------
# Config + client
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> tuple[list[Agent], dict]:
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    agents = _dicts_to_agents(raw.get("agents", []))
    return agents, raw.get("settings", {})


def _dicts_to_agents(agent_dicts: list[dict]) -> list[Agent]:
    """Convert a list of agent config dicts (from YAML or personalities module) to Agent objects."""
    agents = []
    for a in agent_dicts:
        # Resolve optional job_role
        job_role_raw = a.get("job_role")
        job_role: JobRole | None = None
        if isinstance(job_role_raw, JobRole):
            job_role = job_role_raw
        elif isinstance(job_role_raw, str):
            for jr in JobRole:
                if jr.value.lower() == job_role_raw.lower() or jr.name.lower() == job_role_raw.lower():
                    job_role = jr
                    break

        system_prompt = textwrap.dedent(a["system_prompt"]).strip()

        # Inject job-role instructions if a role is assigned and not already present
        # (avoids duplication when generate_mbti_personality already injected it)
        if job_role is not None:
            role_instruction = JOB_ROLE_INSTRUCTIONS.get(job_role)
            if role_instruction and role_instruction not in system_prompt:
                system_prompt = system_prompt + "\n\n" + role_instruction

        agents.append(Agent(
            name=a["name"],
            role=a["role"],
            system_prompt=system_prompt,
            color=a.get("color", "cyan"),
            model=a.get("model"),
            job_role=job_role,
        ))
    return agents


def _build_generated_agents(generated_data: list[dict] | None, topic: str = "") -> list[Agent]:
    """Build Agent objects from generated persona data.

    Returns an empty list when no generated data is provided.
    """
    if not generated_data:
        return []

    agent_dicts = build_agent_panel(
        PersonalityMode.GENERATED,
        base_agents=[],
        topic=topic,
        generated_data=generated_data,
    )
    return _dicts_to_agents(agent_dicts)


def _merge_agents_prefer_first(*groups: list[Agent]) -> list[Agent]:
    """Merge agent groups by name (case-insensitive), preserving first occurrence."""
    merged: list[Agent] = []
    seen_names: set[str] = set()

    for group in groups:
        for agent in group:
            key = agent.name.strip().casefold()
            if key in seen_names:
                continue
            seen_names.add(key)
            merged.append(agent)

    return merged


def _resolve_default_agents(
    base_agents: list[Agent],
    generated_data: list[dict] | None,
    topic: str = "",
) -> list[Agent]:
    """Default panel: YAML agents plus active generated personas appended."""
    generated_agents = _build_generated_agents(generated_data, topic=topic)
    return _merge_agents_prefer_first(base_agents, generated_agents)


_openrouter_client: AsyncOpenAI | None = None
_xai_client: AsyncOpenAI | None = None


def _get_openrouter_client() -> AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            console.print(
                Panel(
                    "[bold red]OPENROUTER_API_KEY not set.[/]\n"
                    "Add it to [bold].env[/] or export it:\n"
                    "  [dim]export OPENROUTER_API_KEY=your_key_here[/]",
                    title="Missing API Key",
                    border_style="red",
                )
            )
            sys.exit(1)
        _openrouter_client = AsyncOpenAI(
            api_key=api_key,
            base_url=API_BASE,
            default_headers={
                "HTTP-Referer": "https://github.com/TheCouncil",
                "X-Title": "TheCouncil",
            },
        )
    return _openrouter_client


def _get_xai_client() -> AsyncOpenAI:
    global _xai_client
    if _xai_client is None:
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            console.print(
                Panel(
                    "[bold red]XAI_API_KEY not set.[/]\n"
                    "Add it to [bold].env[/] for Grok models:\n"
                    "  [dim]export XAI_API_KEY=your_key_here[/]",
                    title="Missing XAI API Key",
                    border_style="red",
                )
            )
            sys.exit(1)
        _xai_client = AsyncOpenAI(api_key=api_key, base_url=XAI_API_BASE)
    return _xai_client


def get_client_for_model(model: str) -> tuple[Any, str]:
    """Return (client, resolved_model) for the given model.

    Resolution order:
    1. Anthropic SDK — when ANTHROPIC_API_KEY is set and model is a Claude model.
    2. XAI native API — when XAI_API_KEY is set and model is a Grok model.
    3. OpenRouter — all other models (default fallback).
    """
    from council.providers.anthropic_provider import (
        get_anthropic_adapter,
        is_claude_model,
        resolve_claude_model,
    )

    model = (model or MODEL).split(":")[0]

    if is_claude_model(model) and os.getenv("ANTHROPIC_API_KEY"):
        adapter = get_anthropic_adapter()
        if adapter is not None:
            return adapter, resolve_claude_model(model)

    if model in XAI_MODEL_MAP and os.getenv("XAI_API_KEY"):
        return _get_xai_client(), XAI_MODEL_MAP[model]

    return _get_openrouter_client(), model


def load_generated_people(path: Path) -> list[dict]:
    """Load generated persona entries from disk.

    Returns an empty list when file does not exist.
    Raises ValueError when file shape is invalid.
    """
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load people file '{path}': {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("People file must contain a JSON array of person objects.")

    for idx, person in enumerate(data):
        if not isinstance(person, dict):
            raise ValueError(f"Person at index {idx} is not an object.")
        if "name" not in person or "data" not in person:
            raise ValueError(
                f"Person at index {idx} must include 'name' and 'data' fields."
            )
        if "active" in person and not isinstance(person["active"], bool):
            raise ValueError(
                f"Person at index {idx} has non-boolean 'active'. Use true or false."
            )
    return data


def save_generated_people(path: Path, people: list[dict]) -> None:
    """Write generated personas to disk in a stable JSON format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(people, f, indent=2, ensure_ascii=True)
        f.write("\n")


def _resolve_people_path(path_from_cli: Path | None) -> Path:
    return path_from_cli or DEFAULT_GENERATED_PEOPLE_FILE


def _extract_json_object(raw: str) -> dict:
    """Extract and parse the first JSON object from model output."""
    text = raw.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced_match:
        text = fenced_match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Model did not return a valid JSON object.")
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("Model output JSON must be an object.")
    return parsed


def _ask_text(question: str, *, allow_empty: bool = False) -> str:
    while True:
        answer = console.input(question).strip()
        if answer or allow_empty:
            return answer
        console.print("[dim]Please enter a value.[/]")


def _ask_yes_no(question: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        answer = console.input(f"{question} {suffix} ").strip().lower()
        if not answer:
            return default_yes
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        console.print("[dim]Please answer yes or no.[/]")


def _ask_choice(question: str, options: list[str], default: str | None = None) -> str:
    option_text = "/".join(options)
    default_suffix = f" [{default}]" if default else ""
    valid = {opt.lower(): opt for opt in options}
    while True:
        answer = console.input(f"{question} ({option_text}){default_suffix}: ").strip().lower()
        if not answer and default:
            return default
        if answer in valid:
            return valid[answer]
        console.print(f"[dim]Choose one of: {', '.join(options)}[/]")


def _ask_list(question: str, *, minimum_items: int = 1, allow_empty: bool = False) -> list[str]:
    while True:
        raw = console.input(question).strip()
        if not raw and allow_empty:
            return []
        values = [v.strip() for v in raw.split(",") if v.strip()]
        if len(values) >= minimum_items:
            return values
        if allow_empty and not raw:
            return []
        console.print(
            f"[dim]Please provide at least {minimum_items} item(s), comma-separated.[/]"
        )


def _ask_multiline(question: str, *, min_chars: int = 0, allow_empty: bool = False) -> str:
    console.print(question)
    console.print("[dim]Enter one or more lines. Submit an empty line to finish.[/]")
    lines: list[str] = []
    while True:
        line = console.input("  > ")
        if not line.strip() and lines:
            break
        if not line.strip() and not lines and allow_empty:
            return ""
        lines.append(line)
    text = "\n".join(lines).strip()
    if len(text) < min_chars and not (allow_empty and not text):
        console.print(f"[dim]Please provide at least {min_chars} characters.[/]")
        return _ask_multiline(question, min_chars=min_chars, allow_empty=allow_empty)
    return text


def _normalize_mbti(value: str) -> str | None:
    v = value.strip().upper()
    if not v:
        return None
    if re.fullmatch(r"[IE][NS][FT][JP]", v):
        return v
    return None


def _collect_attachments_interactive() -> dict[str, Any]:
    """Collect file, directory, URL, and manual text attachments.

    This is a CLI-friendly substitute for file uploads.
    """
    max_files = 20
    max_chars_per_file = 8000
    file_entries: list[dict[str, Any]] = []
    link_entries: list[dict[str, str]] = []
    manual_entries: list[dict[str, str]] = []

    console.print()
    console.print(
        Panel(
            "[bold]Attachments[/]\n"
            "[dim]You can attach local files/directories, add URLs, and paste excerpts. "
            "For directories, up to 20 text files are ingested.[/]",
            border_style="blue",
        )
    )

    while len(file_entries) < max_files:
        path_raw = _ask_text(
            "File or directory path to attach (blank to continue): ", allow_empty=True
        )
        if not path_raw:
            break

        path = Path(path_raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.exists():
            console.print(f"[dim]Path does not exist: {path}[/]")
            continue

        candidates: list[Path]
        if path.is_dir():
            all_files = [p for p in path.rglob("*") if p.is_file()]
            candidates = all_files[: max_files - len(file_entries)]
        else:
            candidates = [path]

        for file_path in candidates:
            if len(file_entries) >= max_files:
                break
            try:
                raw = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                file_entries.append({
                    "path": str(file_path),
                    "read_ok": False,
                    "error": str(exc),
                    "char_count": 0,
                    "excerpt": "",
                })
                continue
            excerpt = raw[:max_chars_per_file]
            file_entries.append({
                "path": str(file_path),
                "read_ok": True,
                "error": "",
                "char_count": len(raw),
                "excerpt": excerpt,
            })

    while True:
        url = _ask_text("URL/social post link to attach (blank to continue): ", allow_empty=True)
        if not url:
            break
        note = _ask_text("Optional note about this link: ", allow_empty=True)
        link_entries.append({"url": url, "note": note})

    while True:
        source = _ask_text(
            "Manual excerpt source label (blank to finish manual excerpts): ",
            allow_empty=True,
        )
        if not source:
            break
        excerpt = _ask_multiline(
            "Paste the excerpt/content to include:",
            min_chars=20,
            allow_empty=False,
        )
        manual_entries.append({"source": source, "excerpt": excerpt})

    chunks: list[str] = []
    if file_entries:
        for entry in file_entries:
            if entry["read_ok"]:
                chunks.append(
                    f"FILE: {entry['path']}\n"
                    f"TOTAL_CHARS: {entry['char_count']}\n"
                    "---BEGIN FILE EXCERPT---\n"
                    f"{entry['excerpt']}\n"
                    "---END FILE EXCERPT---"
                )
            else:
                chunks.append(
                    f"FILE: {entry['path']}\nUNREADABLE: {entry['error']}"
                )
    if link_entries:
        chunks.append(
            "LINKS:\n" + "\n".join(
                f"- {item['url']}" + (f"  | NOTE: {item['note']}" if item["note"] else "")
                for item in link_entries
            )
        )
    if manual_entries:
        for item in manual_entries:
            chunks.append(
                f"MANUAL EXCERPT SOURCE: {item['source']}\n"
                "---BEGIN MANUAL EXCERPT---\n"
                f"{item['excerpt']}\n"
                "---END MANUAL EXCERPT---"
            )

    return {
        "files": file_entries,
        "links": link_entries,
        "manual_excerpts": manual_entries,
        "context_bundle": "\n\n".join(chunks),
        "summary": {
            "file_count": len(file_entries),
            "link_count": len(link_entries),
            "manual_excerpt_count": len(manual_entries),
        },
    }


def _build_full_questionnaire() -> dict[str, Any]:
    """Run complete branched interview and return a structured questionnaire payload."""
    console.print()
    console.print(
        Panel(
            "[bold]Questionnaire[/]\n"
            "[dim]This is a full profile interview. Some questions branch based on your answers.[/]",
            border_style="blue",
        )
    )

    name = _ask_text("Name: ")
    alias = _ask_text("Alias/handle (optional): ", allow_empty=True)
    pronouns = _ask_text("Pronouns (optional): ", allow_empty=True)
    location_context = _ask_text("Region/timezone context (optional): ", allow_empty=True)
    color = _ask_text(
        "Preferred color (blue/red/green/yellow/magenta/cyan/gold/white) [cyan]: ",
        allow_empty=True,
    ) or "cyan"
    mbti_input = _ask_text("Known MBTI (optional, e.g. INTJ): ", allow_empty=True)
    mbti_type = _normalize_mbti(mbti_input)

    primary_domain = _ask_text(
        "Primary domain (engineering, business, policy, research, design, ops, etc.): "
    )
    secondary_domains = _ask_list(
        "Secondary domains (comma separated, optional): ",
        minimum_items=1,
        allow_empty=True,
    )
    years_experience = _ask_text("Years of experience (total): ")
    signature_experiences = _ask_list(
        "Signature experiences/projects (comma separated, at least 2): ",
        minimum_items=2,
    )

    decision_style = _ask_choice(
        "Primary decision style",
        ["analytical", "intuitive", "hybrid", "consensus-driven", "first-principles"],
        default="hybrid",
    )
    risk_tolerance = _ask_choice(
        "Risk tolerance",
        ["low", "medium", "high"],
        default="medium",
    )
    pace_preference = _ask_choice(
        "Decision pace",
        ["deliberate", "balanced", "fast"],
        default="balanced",
    )

    branch_answers: dict[str, Any] = {}
    if risk_tolerance == "high":
        branch_answers["risk_branch"] = {
            "failure_recovery": _ask_multiline(
                "When a risky bet fails, how do you recover and communicate it?",
                min_chars=60,
            ),
            "acceptable_downside": _ask_text("What downside is acceptable for high-upside bets? "),
        }
    elif risk_tolerance == "low":
        branch_answers["risk_branch"] = {
            "evidence_threshold": _ask_multiline(
                "What evidence threshold do you need before committing?",
                min_chars=60,
            ),
            "fallback_strategy": _ask_text("What fallback plans do you always prepare? "),
        }
    else:
        branch_answers["risk_branch"] = {
            "switch_trigger": _ask_multiline(
                "How do you decide when to move from analysis to action?",
                min_chars=60,
            ),
            "calibration_method": _ask_text("How do you calibrate confidence under uncertainty? "),
        }

    if pace_preference == "fast":
        branch_answers["pace_branch"] = {
            "guardrails": _ask_text("What guardrails prevent rushed mistakes? "),
        }
    elif pace_preference == "deliberate":
        branch_answers["pace_branch"] = {
            "anti-analysis-paralysis": _ask_text("How do you avoid analysis paralysis? "),
        }
    else:
        branch_answers["pace_branch"] = {
            "balance_strategy": _ask_text("How do you balance speed and depth in practice? "),
        }

    leads_people = _ask_yes_no("Do you regularly lead teams or organizations?")
    if leads_people:
        branch_answers["leadership_branch"] = {
            "leadership_style": _ask_text("Leadership style in one line: "),
            "conflict_handling": _ask_multiline(
                "How do you handle conflict and underperformance?",
                min_chars=60,
            ),
            "delegation": _ask_text("How do you delegate high-stakes work? "),
        }
    else:
        branch_answers["individual_contributor_branch"] = {
            "influence_strategy": _ask_multiline(
                "How do you influence outcomes without formal authority?",
                min_chars=60,
            ),
            "collaboration_pattern": _ask_text("How do you collaborate with leaders/stakeholders? "),
        }

    domain_key = primary_domain.lower()
    if any(k in domain_key for k in ["engineer", "software", "ai", "ml", "data"]):
        branch_answers["domain_branch"] = {
            "architecture_bias": _ask_text("Preferred architecture bias (simple, modular, experimental, etc.): "),
            "debt_vs_speed": _ask_multiline("How do you trade off technical debt vs delivery speed?", min_chars=60),
            "reliability_principles": _ask_text("Top reliability principles you insist on: "),
        }
    elif any(k in domain_key for k in ["finance", "ops", "operations", "business"]):
        branch_answers["domain_branch"] = {
            "north_star_metric": _ask_text("Primary metric you trust most: "),
            "efficiency_tradeoffs": _ask_multiline("How do you balance growth vs efficiency?", min_chars=60),
            "resource_allocation": _ask_text("How do you allocate constrained resources? "),
        }
    elif any(k in domain_key for k in ["policy", "regulation", "government", "legal"]):
        branch_answers["domain_branch"] = {
            "policy_frame": _ask_text("Policy framing lens you use most: "),
            "stakeholder_balance": _ask_multiline("How do you balance stakeholder interests under uncertainty?", min_chars=60),
            "compliance_vs_innovation": _ask_text("How do you handle compliance vs innovation tension? "),
        }
    elif any(k in domain_key for k in ["research", "science", "academic"]):
        branch_answers["domain_branch"] = {
            "evidence_standard": _ask_text("Evidence standard for accepting claims: "),
            "hypothesis_strategy": _ask_multiline("How do you design and revise hypotheses?", min_chars=60),
            "reproducibility": _ask_text("How do you ensure reproducibility or rigor? "),
        }
    else:
        branch_answers["domain_branch"] = {
            "quality_principle": _ask_text("What principle defines high quality in your craft? "),
            "creative_tradeoffs": _ask_multiline("How do you balance originality with execution constraints?", min_chars=60),
            "feedback_model": _ask_text("How do you incorporate critical feedback? "),
        }

    communication_tone = _ask_text("Communication tone (direct, diplomatic, energetic, etc.): ")
    communication_no_go = _ask_list(
        "Communication no-go behaviors (comma separated, optional): ",
        minimum_items=1,
        allow_empty=True,
    )
    persuasion_style = _ask_text("Persuasion style in debate: ")
    stress_response = _ask_text("How do you respond under pressure? ")
    trigger_topics = _ask_list(
        "Topics that trigger strong reactions (optional, comma separated): ",
        minimum_items=1,
        allow_empty=True,
    )

    core_values = _ask_list("Core values (comma separated, at least 3): ", minimum_items=3)
    non_negotiables = _ask_list(
        "Non-negotiables in decision making (comma separated, at least 2): ",
        minimum_items=2,
    )
    ethical_boundaries = _ask_multiline(
        "Ethical boundaries you will not cross:",
        min_chars=60,
    )

    known_topics = _ask_list("Topics you know deeply (comma separated, at least 4): ", minimum_items=4)
    weak_topics = _ask_list(
        "Areas where you are weaker (optional, comma separated): ",
        minimum_items=1,
        allow_empty=True,
    )
    contrarian_views = _ask_multiline(
        "Strongly held contrarian views (optional):",
        min_chars=0,
        allow_empty=True,
    )
    debate_goals = _ask_multiline("What outcomes do you optimize for in debates?", min_chars=60)
    signature_phrases = _ask_list(
        "Signature phrases/words you often use (optional, comma separated): ",
        minimum_items=1,
        allow_empty=True,
    )

    attachments = _collect_attachments_interactive()

    return {
        "identity": {
            "name": name,
            "alias": alias,
            "pronouns": pronouns,
            "location_context": location_context,
            "color": color,
            "mbti_type": mbti_type,
            "primary_domain": primary_domain,
            "secondary_domains": secondary_domains,
            "years_experience": years_experience,
            "signature_experiences": signature_experiences,
        },
        "cognition": {
            "decision_style": decision_style,
            "risk_tolerance": risk_tolerance,
            "pace_preference": pace_preference,
            "stress_response": stress_response,
        },
        "communication": {
            "tone": communication_tone,
            "persuasion_style": persuasion_style,
            "no_go_behaviors": communication_no_go,
            "signature_phrases": signature_phrases,
        },
        "values": {
            "core_values": core_values,
            "non_negotiables": non_negotiables,
            "ethical_boundaries": ethical_boundaries,
        },
        "knowledge": {
            "deep_topics": known_topics,
            "weak_topics": weak_topics,
            "contrarian_views": contrarian_views,
            "goals": debate_goals,
            "trigger_topics": trigger_topics,
        },
        "branches": branch_answers,
        "attachments": attachments,
    }


def _normalize_generated_persona(
    generated: dict[str, Any],
    questionnaire: dict[str, Any],
    attachments: dict[str, Any],
) -> dict[str, Any]:
    """Normalize model output to required schema and enforce defaults."""
    identity = questionnaire["identity"]
    knowledge = questionnaire["knowledge"]
    communication = questionnaire["communication"]
    values = questionnaire["values"]

    profile = generated.get("profile")
    if not isinstance(profile, dict):
        profile = {}

    normalized = {
        "name": str(generated.get("name") or identity["name"]),
        "role": "Generated Persona",
        "color": str(generated.get("color") or identity["color"] or "cyan"),
        "active": bool(generated.get("active", True)),
        "data": str(generated.get("data") or "").strip(),
        "mbti_type": generated.get("mbti_type") or identity.get("mbti_type"),
        "model": PROFILE_BUILDER_MODEL,
        "profile": {
            "traits": [str(x) for x in profile.get("traits", []) if str(x).strip()] or ["adaptable", "evidence-aware"],
            "reasoning_style": str(profile.get("reasoning_style") or questionnaire["cognition"]["decision_style"]),
            "communication_tone": str(profile.get("communication_tone") or communication["tone"]),
            "knowledge_domains": [str(x) for x in profile.get("knowledge_domains", []) if str(x).strip()] or list(knowledge["deep_topics"]),
            "values": [str(x) for x in profile.get("values", []) if str(x).strip()] or list(values["core_values"]),
            "debate_behaviors": [str(x) for x in profile.get("debate_behaviors", []) if str(x).strip()] or [
                f"Optimizes for {knowledge['goals'][:120]}",
                f"Uses persuasion style: {communication['persuasion_style']}",
            ],
            "blind_spots": [str(x) for x in profile.get("blind_spots", []) if str(x).strip()] or list(knowledge["weak_topics"]),
        },
        "sources": {
            "links": [item["url"] for item in attachments.get("links", []) if item.get("url")],
            "files": [item["path"] for item in attachments.get("files", []) if item.get("path")],
            "manual_excerpts": [item.get("source", "") for item in attachments.get("manual_excerpts", [])],
        },
        "questionnaire": questionnaire,
        "attachment_summary": attachments.get("summary", {}),
    }

    if not normalized["data"]:
        normalized["data"] = textwrap.dedent(
            f"""
            Identity: {normalized['name']} ({identity['primary_domain']}).
            Decision style: {questionnaire['cognition']['decision_style']}. Risk tolerance: {questionnaire['cognition']['risk_tolerance']}.
            Communication: {questionnaire['communication']['tone']} with persuasion style {questionnaire['communication']['persuasion_style']}.
            Core values: {', '.join(values['core_values'])}.
            Deep expertise: {', '.join(knowledge['deep_topics'])}.
            Debate objective: {knowledge['goals']}.
            """
        ).strip()
    return normalized


async def run_persona_questionnaire(output_path: Path) -> None:
    """Interactive full questionnaire that builds a comprehensive generated persona JSON entry."""
    console.print()
    console.print(
        Panel(
            "[bold]Generated Persona Questionnaire[/]\n"
            "[dim]This wizard runs a full branched interview, ingests attachments, "
            "and builds a comprehensive persona profile using "
            f"{PROFILE_BUILDER_MODEL} and saves it into your people JSON file.[/]",
            border_style="blue",
        )
    )

    questionnaire_payload = _build_full_questionnaire()
    attachments = questionnaire_payload["attachments"]

    model_prompt = textwrap.dedent(
        """
        You are building a comprehensive generated persona profile for a council debate system.
        Return ONE JSON object only (no markdown) with this schema:
        {
          "name": string,
          "role": "Generated Persona",
          "color": string,
          "active": boolean,
          "data": string,
          "mbti_type": string|null,
          "model": string,
          "profile": {
            "traits": [string],
            "reasoning_style": string,
            "communication_tone": string,
            "knowledge_domains": [string],
            "values": [string],
            "debate_behaviors": [string],
            "blind_spots": [string]
          },
          "sources": {
            "links": [string],
                        "files": [string],
                        "manual_excerpts": [string]
                    },
                    "questionnaire": object,
                    "attachment_summary": object
        }

        Rules:
        - "active" must be true by default.
        - "model" must be exactly "x-ai/grok-4-1-fast-non-reasoning".
        - "data" must be a rich, concrete textual profile (8-14 paragraphs) synthesizing identity,
          thinking style, expertise, communication, values, and notable evidence from attachments.
                - Infer likely blind spots and debate failure modes from the questionnaire, not stereotypes.
                - Keep tone and vocabulary aligned with the user's stated communication style.
        - Keep all claims grounded in the provided questionnaire and attachments.
        - If MBTI not provided, set "mbti_type" to null.
        """
    ).strip()

    input_msgs = [
        {"role": "system", "content": model_prompt},
        {"role": "user", "content": json.dumps(questionnaire_payload, ensure_ascii=True, indent=2)},
    ]
    raw = await api_call(input_msgs, max_tokens=2400, model=PROFILE_BUILDER_MODEL)
    try:
        generated_raw = _extract_json_object(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        console.print(
            Panel(
                f"[bold red]Model output could not be parsed as persona JSON:[/]\n{exc}\n\n"
                "[dim]You can re-run the questionnaire and try again.[/]",
                title="Persona Build Error",
                border_style="red",
            )
        )
        return

    generated = _normalize_generated_persona(
        generated_raw,
        questionnaire_payload,
        attachments,
    )

    people = load_generated_people(output_path)
    existing_index = next(
        (idx for idx, person in enumerate(people) if str(person.get("name", "")).lower() == generated["name"].lower()),
        None,
    )
    if existing_index is not None:
        people[existing_index] = generated
    else:
        people.append(generated)
    save_generated_people(output_path, people)

    console.print()
    console.print(
        Panel(
            f"[bold green]Persona saved.[/]\n"
            f"Name: {generated['name']}\n"
            f"Active: {generated['active']}\n"
            f"Attachments: files={attachments['summary']['file_count']}, "
            f"links={attachments['summary']['link_count']}, "
            f"manual={attachments['summary']['manual_excerpt_count']}\n"
            f"File: {output_path}\n"
            f"Model: {PROFILE_BUILDER_MODEL}",
            border_style="green",
            title="Generated Persona",
        )
    )


def set_persona_active(path: Path, name: str, active: bool) -> bool:
    """Toggle active state for a generated persona by name.

    Returns True if a persona was updated, else False.
    """
    people = load_generated_people(path)
    for person in people:
        person_name = str(person.get("name", ""))
        if person_name.lower() == name.lower():
            person["active"] = active
            save_generated_people(path, people)
            return True
    return False


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

# Cost efficiency: truncate older round responses when context grows. Same char budget as
# a single tail slice, but keep opening + closing so votes and later rounds still see thesis + conclusion.
_TRUNCATE_RESPONSE_CHARS = 420


def _truncate_response(content: str, max_chars: int = _TRUNCATE_RESPONSE_CHARS) -> str:
    """Truncate long responses for cost efficiency, preserving start + end (same budget as one slice)."""
    content = content.strip()
    if len(content) <= max_chars:
        return content
    sep = "\n… [earlier detail omitted] …\n"
    inner = max_chars - len(sep)
    if inner < 120:
        return content[: max_chars - 20].rsplit(maxsplit=1)[0] + "… [truncated]"
    head_budget = int(inner * 0.62)
    tail_budget = inner - head_budget
    head = content[:head_budget].rsplit(maxsplit=1)[0]
    tail = content[-tail_budget:].strip()
    # Avoid starting tail mid-word when possible
    if " " in tail[:24]:
        tail = tail[tail.find(" ") + 1 :].strip()
    if len(head) + len(sep) + len(tail) > max_chars + 40:
        return content[: max_chars - 20].rsplit(maxsplit=1)[0] + "… [truncated]"
    return head + sep + tail


def build_transcript(
    session: DebateSession,
    up_to_round: int,
    truncate_rounds_before: int | None = None,
) -> str:
    """Build public transcript from all rounds strictly before up_to_round.
    When truncate_rounds_before is set (e.g. 3), rounds before that get truncated responses."""
    ROUND_LABELS = {
        1: "Round 1 — Independent Takes",
        2: "Round 2 — Cross-Debate I",
        3: "Round 3 — Private Deliberation",
        4: "Round 4 — Cross-Debate II",
    }
    parts = []
    for responses in session.rounds:
        if not responses:
            continue
        rn = responses[0].round_num
        if rn >= up_to_round:
            break
        truncate = truncate_rounds_before is not None and rn < truncate_rounds_before
        label = ROUND_LABELS.get(rn, f"Round {rn} — Tie-Breaker Debate" if rn >= 5 else f"Round {rn}")
        parts.append(f"## {label}\n")
        for r in responses:
            content = _truncate_response(r.content) if truncate else r.content
            parts.append(f"### {r.agent.name} ({r.agent.role}):\n{content}\n")
    return "\n".join(parts)


def pop_inbox(session: DebateSession, agent_name: str) -> str:
    """Pop and format all pending DMs for this agent. Returns empty string if none."""
    messages: list[tuple[str, str]] = session.inbox.pop(agent_name, [])  # type: ignore[arg-type]
    if not messages:
        return ""
    lines = ["\n\n---\nPRIVATE MESSAGES (visible only to you):"]
    for sender, content in messages:
        lines.append(f"\nFrom {sender} (private): {content}")
    lines.append("---")
    return "\n".join(lines)


def deliver_dm(dm: DM, session: DebateSession) -> None:
    session.inbox[dm.recipient].append((dm.sender, dm.content))
    session.dms.append(dm)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def api_call(
    input_msgs: Sequence[dict],
    max_tokens: int = 1024,
    model: str | None = None,
) -> str:
    """Non-streaming async call. Returns full output text. Routes to XAI or OpenRouter based on model."""
    client, resolved_model = get_client_for_model(model or MODEL)
    response = await client.responses.create(
        model=resolved_model,
        input=cast(Any, list(input_msgs)),
        max_output_tokens=max_tokens,
    )
    return response.output_text or ""


async def api_stream(
    input_msgs: Sequence[dict],
    max_tokens: int = 1024,
    model: str | None = None,
) -> str:
    """Streaming async call — prints tokens live. Use only in sequential context."""
    client, resolved_model = get_client_for_model(model or MODEL)
    collected: list[str] = []
    async with client.responses.stream(
        model=resolved_model,
        input=cast(Any, list(input_msgs)),
        max_output_tokens=max_tokens,
    ) as stream:
        async for event in stream:
            if event.type == "response.output_text.delta":
                delta = event.delta or ""
                if delta:
                    collected.append(delta)
                    console.print(delta, end="", markup=False)
    console.print()
    return "".join(collected)


# ---------------------------------------------------------------------------
# DM system
# ---------------------------------------------------------------------------

_DM_SINGLE_PROMPT = """\
You have completed your public response. You may now send ONE private message \
to a single council member. This is completely secret — no one else will ever \
see it. It will be delivered as private context before their next response.

You may only sway them with logic and earnest appeal (e.g. begging, pleading for their vote). \
No bribes — no money, cryptocurrency, favors, or promises of resources. Nothing of monetary value. Use reason and persuasion only.

Available recipients: {recipients}

WORD LIMIT: Your message must be 50 words or fewer. Every word counts — be sharp and direct.

To send a DM, reply in EXACTLY this format:
TO: [exact agent name from the list above]
MESSAGE: [your private message — max 50 words]

To send nothing, reply exactly:
NO DM"""

_DM_MULTI_PROMPT = """\
This is a PRIVATE DELIBERATION ROUND. You will not give a public response. \
Instead, send private messages to any council member(s) you choose. \
Use this to share private concerns, make logical arguments, or appeal earnestly (e.g. beg, plead) for their vote. No bribes — no money, cryptocurrency, favors, or promises of resources. Nothing of monetary value. Logic and persuasion only.

Available recipients: {recipients}

WORD LIMIT: Each individual message must be 50 words or fewer. Every word counts — be sharp and direct.

Format (repeat for each DM):
---DM---
TO: [agent name]
MESSAGE: [your message — max 50 words]
---END---

If you have nothing to communicate privately, reply exactly:
NOTHING TO SAY"""


def _parse_single_dm(raw: str, sender: Agent, session: DebateSession, round_num: int) -> DM | None:
    raw = raw.strip()
    if not raw or raw.upper().startswith("NO DM") or "NO DM" in raw[:25].upper():
        return None

    to_line = ""
    message_lines: list[str] = []
    in_message = False

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("TO:") and not to_line:
            to_line = stripped[3:].strip().strip('"').strip("'")
        elif stripped.upper().startswith("MESSAGE:"):
            in_message = True
            message_lines.append(stripped[8:].strip())
        elif in_message:
            message_lines.append(stripped)

    valid_names = {a.name for a in session.agents if a.name != sender.name}
    matched = next(
        (n for n in valid_names if n.lower() in to_line.lower() or to_line.lower() in n.lower()),
        None,
    )
    if not matched or not any(message_lines):
        return None

    return DM(
        sender=sender.name,
        recipient=matched,
        content="\n".join(message_lines).strip(),
        round_num=round_num,
    )


def _parse_multi_dm(raw: str, sender: Agent, session: DebateSession, round_num: int) -> list[DM]:
    raw = raw.strip()
    if not raw or "NOTHING TO SAY" in raw[:30].upper():
        return []

    dms: list[DM] = []
    valid_names = {a.name for a in session.agents if a.name != sender.name}

    for block in raw.split("---DM---"):
        if "---END---" not in block:
            continue
        block = block.split("---END---")[0].strip()

        to_line = ""
        message_lines: list[str] = []
        in_message = False

        for line in block.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("TO:") and not to_line:
                to_line = stripped[3:].strip().strip('"').strip("'")
            elif stripped.upper().startswith("MESSAGE:"):
                in_message = True
                message_lines.append(stripped[8:].strip())
            elif in_message:
                message_lines.append(stripped)

        matched = next(
            (n for n in valid_names if n.lower() in to_line.lower() or to_line.lower() in n.lower()),
            None,
        )
        if matched and any(message_lines):
            dms.append(DM(
                sender=sender.name,
                recipient=matched,
                content="\n".join(message_lines).strip(),
                round_num=round_num,
            ))

    return dms


async def _attempt_dm(
    agent: Agent,
    session: DebateSession,
    round_num: int,
    public_response: str,
    prior_ctx: str,
) -> DM | None:
    """After a public response, ask agent if they want to DM someone."""
    other_names = ", ".join(f'"{a.name}"' for a in session.agents if a.name != agent.name)
    dm_prompt = _DM_SINGLE_PROMPT.format(recipients=other_names)

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Question under debate: {session.question}\n\n"
            f"{prior_ctx}\n\n"
            f"Your public response:\n{public_response}\n\n"
            f"{dm_prompt}"
        )},
    ]
    model = agent.model or session.model
    raw = await api_call(input_msgs, max_tokens=120, model=model)
    return _parse_single_dm(raw, agent, session, round_num)


async def _dm_only_round(
    agent: Agent,
    session: DebateSession,
) -> list[DM]:
    """Round 3: agent generates private DMs, no public output."""
    prior_ctx = build_transcript(session, up_to_round=99, truncate_rounds_before=3)
    inbox_ctx = pop_inbox(session, agent.name)
    other_names = ", ".join(f'"{a.name}"' for a in session.agents if a.name != agent.name)
    dm_prompt = _DM_MULTI_PROMPT.format(recipients=other_names)

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Question under debate: {session.question}\n\n"
            f"Full public debate transcript:\n{prior_ctx}"
            f"{inbox_ctx}\n\n"
            f"{dm_prompt}"
        )},
    ]
    # 4 agents × (header + 50-word message) = ~120 tokens each, 480 max for all DMs
    model = agent.model or session.model
    raw = await api_call(input_msgs, max_tokens=480, model=model)
    return _parse_multi_dm(raw, agent, session, 4)


# ---------------------------------------------------------------------------
# Round runners
# ---------------------------------------------------------------------------

async def _agent_round1(
    agent: Agent,
    session: DebateSession,
) -> tuple[AgentResponse, DM | None]:
    """Round 1: independent take (parallel, non-streaming)."""
    inbox_ctx = pop_inbox(session, agent.name)

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"The council has been asked to evaluate:\n\n---\n{session.question}\n---\n\n"
            f"Provide your independent analysis. Do not hedge — be direct and specific."
            f"{PERSUASION_NARRATIVE}"
            f"{inbox_ctx}"
        )},
    ]
    model = agent.model or session.model
    content = (await api_call(input_msgs, model=model)).strip()
    response = AgentResponse(agent=agent, round_num=1, content=content)

    dm = await _attempt_dm(agent, session, 1, content, "")
    return response, dm


async def _agent_cross_debate(
    agent: Agent,
    session: DebateSession,
    round_num: int,
    already_responded: list[AgentResponse],
) -> tuple[AgentResponse, DM | None]:
    """Cross-debate round (sequential, streaming). Agent sees prior rounds + already-responded peers."""
    truncate_before = 3 if round_num >= 4 else None
    prior_ctx = build_transcript(session, up_to_round=round_num, truncate_rounds_before=truncate_before)
    inbox_ctx = pop_inbox(session, agent.name)

    # Agents who already spoke in THIS round are appended as "in-progress" context
    in_round_ctx = ""
    if already_responded:
        blocks = "\n\n".join(
            f"### {r.agent.name} (this round, just now):\n{r.content}"
            for r in already_responded
        )
        in_round_ctx = f"\n\n## Responses already given in this round:\n{blocks}"

    round_labels = {2: "Cross-Debate I", 4: "Cross-Debate II"}
    round_label = round_labels.get(round_num, f"Round {round_num}")

    console.print()
    console.rule(
        Text(f"  {agent.name}  ·  {agent.role}  ·  {round_label}  ", style=agent.rich_color)
    )
    console.print()

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Original question:\n\n---\n{session.question}\n---\n\n"
            f"{prior_ctx}{in_round_ctx}\n\n"
            f"Now engage in debate. Respond to the other experts — agree where they are right, "
            f"challenge where they are wrong. Name who you are responding to."
            f"{PERSUASION_NARRATIVE}"
            f"{inbox_ctx}"
        )},
    ]

    model = agent.model or session.model
    start = time.monotonic()
    if session.stream_cross_debate:
        content = (await api_stream(input_msgs, model=model)).strip()
    else:
        content = (await api_call(input_msgs, model=model)).strip()
        console.print(content, markup=False)
    elapsed = time.monotonic() - start
    console.print(f"[dim]└─ {agent.name} finished in {elapsed:.1f}s[/]")

    response = AgentResponse(agent=agent, round_num=round_num, content=content)
    truncate_before = 3 if round_num >= 4 else None
    prior_for_dm = build_transcript(session, up_to_round=round_num, truncate_rounds_before=truncate_before)
    dm = await _attempt_dm(agent, session, round_num, content, prior_for_dm)
    return response, dm


async def _agent_tiebreaker_debate(
    agent: Agent,
    session: DebateSession,
    round_num: int,
    tied_proposers: list[str],
    already_responded: list[AgentResponse],
) -> AgentResponse:
    """Tie-breaker debate: agents discuss only the tied resolutions. No DM."""
    prior_ctx = build_transcript(session, up_to_round=round_num, truncate_rounds_before=5)
    inbox_ctx = pop_inbox(session, agent.name)
    tied_resolutions = "\n\n".join(
        f"**{p}**: {session.resolutions[p]}" for p in tied_proposers
    )
    in_round_ctx = ""
    if already_responded:
        blocks = "\n\n".join(
            f"### {r.agent.name} (this round, just now):\n{r.content}"
            for r in already_responded
        )
        in_round_ctx = f"\n\n## Responses already given in this round:\n{blocks}"

    console.print()
    console.rule(
        Text(
            f"  {agent.name}  ·  {agent.role}  ·  Tie-Breaker Debate  ",
            style=agent.rich_color,
        )
    )
    console.print()

    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": (
            f"Original question:\n\n---\n{session.question}\n---\n\n"
            f"{prior_ctx}{in_round_ctx}\n\n"
            f"These resolutions are TIED for first place. Debate which should win. "
            f"Focus only on these options:\n\n{tied_resolutions}\n\n"
            f"Engage with the other experts. Try to converge on one resolution."
            f"{PERSUASION_NARRATIVE}"
            f"{inbox_ctx}"
        )},
    ]

    model = agent.model or session.model
    start = time.monotonic()
    if session.stream_cross_debate:
        content = (await api_stream(input_msgs, model=model)).strip()
    else:
        content = (await api_call(input_msgs, model=model)).strip()
        console.print(content, markup=False)
    elapsed = time.monotonic() - start
    console.print(f"[dim]└─ {agent.name} finished in {elapsed:.1f}s[/]")

    return AgentResponse(agent=agent, round_num=round_num, content=content)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_header(question: str, agents: list[Agent]) -> None:
    console.print()
    console.print(
        Panel(
            Text("⚖  C O U N C I L", style="bold white", justify="center"),
            subtitle="Mixture-of-Experts Decision Engine",
            border_style="blue",
            padding=(1, 4),
        )
    )
    console.print()
    panel_lines = "\n".join(
        f"  [{a.rich_color}]▸ {a.name}[/]  [dim]{a.role}[/]" for a in agents
    )
    console.print(
        Panel(
            f"[bold]Question:[/]\n  {question}\n\n[bold]Panel:[/]\n{panel_lines}",
            border_style="blue",
            title="[bold blue]Session[/]",
            padding=(1, 2),
        )
    )
    console.print()


def _print_async_responses(responses: list[AgentResponse]) -> None:
    """Display collected async responses one by one."""
    for r in responses:
        console.print()
        console.rule(
            Text(f"  {r.agent.name}  ·  {r.agent.role}  ", style=r.agent.rich_color)
        )
        console.print()
        console.print(r.content, markup=False)
        console.print()


def _print_dm_indicator(dm: DM) -> None:
    console.print()
    console.print(f"  [dim]📨  {dm.sender}  →  {dm.recipient}[/]")
    for line in dm.content.splitlines():
        console.print(f"  [dim]│  {line}[/]", markup=False)
    console.print()


# ---------------------------------------------------------------------------
# Resolution + vote
# ---------------------------------------------------------------------------

_PROPOSE_RESOLUTION_PROMPT = (
    "Based on the debate, propose your own resolution for the council to vote on.\n\n"
    "Write 1–2 substantive paragraphs that express your genuine position. Your resolution must "
    "reflect your persona, MBTI profile, and job role. Use real reasoning and take a clear stand — "
    "no bullet lists, no one-liners, no vague hedging. Write as yourself: your voice, your logic, "
    "your conclusion.\n\n"
    "Begin directly with your resolution text. No preamble, no labels."
)


_VOTE_FOR_ONE_RESOLUTION_PROMPT = """\
Below are the resolutions still in contention. You must vote for exactly ONE.

{resolutions_block}

Review the debate. Pick the resolution you believe is best. You may vote for your own resolution.

Reply with EXACTLY one line in this format:
VOTE: [exact proposer name from the list above]

You may add one short sentence of rationale after the VOTE line if you wish, but the VOTE line must appear first."""


def _compute_vote_counts(votes: dict[str, str]) -> dict[str, int]:
    """Count votes per proposer. votes: voter_name -> proposer_name."""
    counts: dict[str, int] = defaultdict(int)
    for proposer in votes.values():
        if proposer:
            counts[proposer] += 1
    return dict(counts)


def _get_tied_winners(counts: dict[str, int]) -> list[str]:
    """Return proposers with max vote count. Single element if clear winner, 2+ if tie."""
    if not counts:
        return []
    max_count = max(counts.values())
    return [p for p, c in counts.items() if c == max_count]


def _parse_single_preference_vote(raw: str, valid_proposers: set[str]) -> str | None:
    """Extract proposer name from agent response. Returns None if unparseable or invalid."""
    raw_stripped = raw.strip()
    if not raw_stripped or not valid_proposers:
        return None
    # Normalize markdown / bullets that models sometimes add before VOTE:
    cleaned = raw_stripped.replace("**", "").replace("*", "")
    low = cleaned.lower()
    idx = low.find("vote:")
    if idx < 0:
        return None
    rest = cleaned[idx + 5 :].lstrip()
    first_line = rest.split("\n")[0].strip().strip('"\'')
    # Strip trailing parenthetical or em-dash rationale
    for cut in (" — ", " - ", " (", "\t"):
        if cut in first_line:
            first_line = first_line.split(cut)[0].strip()
            break
    if not first_line:
        return None
    fl = first_line.lower().rstrip(".!?:;")
    # Exact match first (case-insensitive), then prefix (e.g. "Red Teamer's resolution")
    for p in valid_proposers:
        if fl == p.lower():
            return p
    for p in sorted(valid_proposers, key=len, reverse=True):
        if fl.startswith(p.lower()):
            return p
    return None


async def _agent_propose_resolution(
    agent: Agent,
    session: DebateSession,
) -> str:
    """Agent proposes their own resolution. Returns resolution text."""
    transcript = build_transcript(session, up_to_round=99, truncate_rounds_before=3)
    user_content = (
        f"Original question:\n\n---\n{session.question}\n---\n\n"
        f"Debate transcript:\n\n{transcript}\n\n"
        f"{_PROPOSE_RESOLUTION_PROMPT}"
    )
    input_msgs = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": user_content},
    ]
    model = agent.model or session.model
    return (await api_call(input_msgs, max_tokens=600, model=model)).strip()


def _build_resolutions_block(resolutions_in_play: list[tuple[str, str]]) -> str:
    """Format resolutions for the vote prompt."""
    lines = []
    for proposer, resolution in resolutions_in_play:
        lines.append(f"Proposed by {proposer}:\n---\n{resolution}\n---")
    return "\n\n".join(lines)


async def _agent_vote_for_one_resolution(
    voter: Agent,
    session: DebateSession,
    resolutions_in_play: list[tuple[str, str]],
) -> str | None:
    """Agent votes for exactly one resolution. Returns proposer name or None if invalid."""
    transcript = build_transcript(session, up_to_round=99, truncate_rounds_before=3)
    resolutions_block = _build_resolutions_block(resolutions_in_play)
    valid_proposers = {p for p, _ in resolutions_in_play}
    user_content = (
        f"Original question:\n\n---\n{session.question}\n---\n\n"
        f"Debate transcript:\n\n{transcript}\n\n"
        f"{_VOTE_FOR_ONE_RESOLUTION_PROMPT.format(resolutions_block=resolutions_block)}"
    )
    input_msgs = [
        {"role": "system", "content": voter.system_prompt},
        {"role": "user", "content": user_content},
    ]
    model = voter.model or session.model
    raw = await api_call(input_msgs, max_tokens=120, model=model)
    return _parse_single_preference_vote(raw, valid_proposers)


# ---------------------------------------------------------------------------
# Top-3 extraction + Moderator analysis
# ---------------------------------------------------------------------------


@dataclass
class ResolutionAnalysis:
    """Structured pros/cons analysis for a single resolution."""

    rank: int
    agent_name: str
    agent_role: str
    resolution: str
    summary: str          # one-sentence distillation
    pros: list[str]       # 2–3 specific pros
    cons: list[str]       # 2–3 specific cons


@dataclass
class ModeratorReport:
    """Output of the Moderator agent: ranked analyses for the top 3 resolutions."""

    analyses: list[ResolutionAnalysis]


def _get_top3_resolutions(session: DebateSession) -> list[tuple[str, str, int]]:
    """Return the top-3 (agent_name, resolution_text, vote_count) by first-round votes.

    Tie at 3rd place is broken by insertion order in session.resolutions.
    Returns up to 3 entries; may be fewer if fewer resolutions exist.
    """
    if not session.vote_rounds:
        # No votes at all — return resolutions in insertion order with 0 votes
        ordered = list(session.resolutions.items())
        return [(name, text, 0) for name, text in ordered[:3]]

    # Use the first vote round (all resolutions in play, most complete tally)
    first_round_votes = session.vote_rounds[0]
    counts = _compute_vote_counts(first_round_votes)

    # Build (name, text, votes) preserving insertion order as secondary sort key
    insertion_order = {name: i for i, name in enumerate(session.resolutions)}
    ranked = sorted(
        ((name, text, counts.get(name, 0)) for name, text in session.resolutions.items()),
        key=lambda x: (-x[2], insertion_order.get(x[0], 0)),
    )
    return ranked[:3]


_MODERATOR_SYSTEM_PROMPT = (
    "You are a neutral Moderator. You have no persona, no vote, and no stake in the outcome. "
    "Your sole purpose is to provide an objective, rigorous analysis of the resolutions "
    "placed before you. You do not favour any agent. You evaluate purely on merit."
)

_MODERATOR_ANALYSIS_PROMPT = """\
You are analysing the top resolutions from a council debate.

ORIGINAL QUESTION:
---
{question}
---

TOP RESOLUTIONS (ranked by votes, highest first):

{resolutions_block}

For EACH resolution above, produce a structured analysis with:
  - summary: one sentence that captures the core idea (not generic praise)
  - pros: exactly 2–3 specific strengths directly tied to the question
  - cons: exactly 2–3 specific weaknesses or risks directly tied to the question

Respond with a valid JSON object in EXACTLY this structure (no extra keys, no markdown fences):

{{
  "analyses": [
    {{
      "rank": 1,
      "summary": "...",
      "pros": ["...", "...", "..."],
      "cons": ["...", "...", "..."]
    }},
    {{
      "rank": 2,
      "summary": "...",
      "pros": ["...", "...", "..."],
      "cons": ["...", "...", "..."]
    }},
    {{
      "rank": 3,
      "summary": "...",
      "pros": ["...", "...", "..."],
      "cons": ["...", "...", "..."]
    }}
  ]
}}

Do not include any text outside the JSON object."""


def _parse_moderator_json(
    raw: str,
    top3: list[tuple[str, str, int]],
    agents: list[Agent],
) -> ModeratorReport:
    """Parse the moderator's JSON response into a ModeratorReport.

    Falls back to placeholder entries if parsing fails.
    """
    agent_by_name: dict[str, Agent] = {a.name: a for a in agents}

    def _make_fallback(rank: int, name: str, text: str) -> ResolutionAnalysis:
        agent = agent_by_name.get(name)
        return ResolutionAnalysis(
            rank=rank,
            agent_name=name,
            agent_role=agent.role if agent else "",
            resolution=text,
            summary="(summary unavailable)",
            pros=["(unavailable)"],
            cons=["(unavailable)"],
        )

    try:
        # Strip markdown fences if the model wrapped the JSON anyway
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned.strip())
        data = json.loads(cleaned)
        raw_analyses = data.get("analyses", [])
    except (json.JSONDecodeError, AttributeError):
        return ModeratorReport(
            analyses=[_make_fallback(i + 1, name, text) for i, (name, text, _) in enumerate(top3)]
        )

    analyses: list[ResolutionAnalysis] = []
    for i, (agent_name, resolution_text, _) in enumerate(top3):
        rank = i + 1
        agent = agent_by_name.get(agent_name)
        # Find matching entry by rank; fall back to positional
        entry: dict = {}
        for a in raw_analyses:
            if isinstance(a, dict) and a.get("rank") == rank:
                entry = a
                break
        if not entry and i < len(raw_analyses) and isinstance(raw_analyses[i], dict):
            entry = raw_analyses[i]
        analyses.append(
            ResolutionAnalysis(
                rank=rank,
                agent_name=agent_name,
                agent_role=agent.role if agent else "",
                resolution=resolution_text,
                summary=str(entry.get("summary", "(summary unavailable)")),
                pros=[str(p) for p in entry.get("pros", ["(unavailable)"])],
                cons=[str(c) for c in entry.get("cons", ["(unavailable)"])],
            )
        )

    # Pad with fallbacks if the model returned fewer than expected
    for i in range(len(analyses), len(top3)):
        agent_name, resolution_text, _ = top3[i]
        analyses.append(_make_fallback(i + 1, agent_name, resolution_text))

    return ModeratorReport(analyses=analyses)


async def _moderator_pros_cons(
    question: str,
    top3: list[tuple[str, str, int]],
    agents: list[Agent],
    model: str,
) -> ModeratorReport:
    """Run the Moderator agent over the top-3 resolutions and return structured analysis."""
    resolutions_block = "\n\n".join(
        f"RANK {rank} — Proposed by {name} ({_agent_role_str(name, agents)}):\n---\n{text}\n---"
        for rank, (name, text, _) in enumerate(top3, start=1)
    )
    user_content = _MODERATOR_ANALYSIS_PROMPT.format(
        question=question,
        resolutions_block=resolutions_block,
    )
    input_msgs = [
        {"role": "system", "content": _MODERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = await api_call(input_msgs, max_tokens=1200, model=model)
    return _parse_moderator_json(raw, top3, agents)


def _agent_role_str(agent_name: str, agents: list[Agent]) -> str:
    """Return the role string for an agent by name, or empty string if not found."""
    for a in agents:
        if a.name == agent_name:
            return a.role
    return ""


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------


async def _generate_dynamic_agents(topic: str, n: int, model: str) -> list[Agent]:
    """Use the LLM to generate ``n`` dynamic agent personas for the given topic."""
    prompt = DYNAMIC_GENERATION_PROMPT.format(topic=topic, n=n)
    input_msgs = [{"role": "user", "content": prompt}]
    raw = await api_call(input_msgs, max_tokens=2000, model=model)
    agent_dicts = parse_dynamic_agents(raw)
    if not agent_dicts:
        # Fallback to canned if LLM didn't return parseable agents
        agent_dicts = get_canned_personalities()
    return _dicts_to_agents(agent_dicts)


async def run_council(
    question: str,
    config_path: Path,
    personality_mode: PersonalityMode | None = None,
    guardrails_enabled: bool = True,
    generated_data: list[dict] | None = None,
) -> None:
    """
    Run a full Council debate session.

    Args:
        question:          The argument/question put to the council.
        config_path:       Path to agents.yaml (used when personality_mode is None).
        personality_mode:  If set, overrides the agent panel with the chosen mode.
                           None means use the YAML config as-is (existing behaviour).
        guardrails_enabled: Screen the question through guardrails before proceeding.
        generated_data:    For PersonalityMode.GENERATED — list of person dicts.
    """
    # ── GUARDRAILS (Feature 5) ────────────────────────────────────────────
    if guardrails_enabled:
        guardrails = Guardrails()
        result = guardrails.screen(question)
        if result.blocked:
            console.print()
            console.print(
                Panel(
                    result.summary(),
                    title="[bold red]🚫 Input Blocked by Guardrails[/]",
                    border_style="red",
                    padding=(1, 2),
                )
            )
            console.print()
            return

    base_agents, settings = load_config(config_path)
    default_model = settings.get("model", MODEL)

    # ── PERSONALITY MODE (Feature 1) ──────────────────────────────────────
    if personality_mode is None:
        agents = _resolve_default_agents(base_agents, generated_data, topic=question)
    elif personality_mode == PersonalityMode.DYNAMIC:
        console.print("\n[dim]Generating dynamic agent personas for this topic…[/]\n")
        agents = await _generate_dynamic_agents(question, n=5, model=default_model)
    elif personality_mode == PersonalityMode.GENERATED:
        agent_dicts = build_agent_panel(
            PersonalityMode.GENERATED,
            base_agents=[],
            topic=question,
            generated_data=generated_data,
        )
        agents = _dicts_to_agents(agent_dicts)
    else:
        # CANNED or HYBRID — synchronous panel build
        agent_dicts = build_agent_panel(
            personality_mode,
            base_agents=[a.__dict__ for a in base_agents],
            topic=question,
        )
        agents = _dicts_to_agents(agent_dicts)

    if not agents:
        console.print("[bold red]No agents defined in config.[/]")
        sys.exit(1)

    session = DebateSession(
        question=question,
        agents=agents,
        model=settings.get("model", MODEL),
        stream_cross_debate=settings.get("stream_cross_debate", True),
        show_dm_indicators=settings.get("show_dm_indicators", True),
    )
    _print_header(question, agents)
    console.print()

    # ── ROUND 1: INDEPENDENT (async parallel) ──────────────────────────────
    console.rule(Text("  ROUND 1 ·  INDEPENDENT TAKES  ", style="bold yellow"), style="yellow")
    console.print("\n[dim]All agents deliberating simultaneously…[/]\n")

    r1_results = await asyncio.gather(
        *[_agent_round1(agent, session) for agent in agents]
    )

    round1_responses = [res for res, _ in r1_results]
    session.rounds.append(round1_responses)
    _print_async_responses(round1_responses)

    for _, dm in r1_results:
        if dm:
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                _print_dm_indicator(dm)

    # ── ROUND 2: CROSS-DEBATE I (sequential, streaming) ───────────────────
    console.print()
    console.rule(Text("  ROUND 2  ·  CROSS-DEBATE I  ", style="bold yellow"), style="yellow")

    round2_responses: list[AgentResponse] = []
    for agent in agents:
        response, dm = await _agent_cross_debate(agent, session, 2, round2_responses)
        round2_responses.append(response)
        if dm:
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                _print_dm_indicator(dm)

    session.rounds.append(round2_responses)

    # ── ROUND 3: PRIVATE DELIBERATION (async parallel, DM-only) ───────────
    console.print()
    console.rule(
        Text("  ROUND 3  ·  PRIVATE DELIBERATION  ", style="bold magenta"), style="magenta"
    )
    console.print("\n[dim]Agents exchanging private messages…[/]\n")

    dm_batches = await asyncio.gather(
        *[_dm_only_round(agent, session) for agent in agents]
    )

    round3_dms: list[DM] = []
    for batch in dm_batches:
        for dm in batch:
            round3_dms.append(dm)
            # Deliver to inbox — agents will see these in Cross-Debate II (also records dm once)
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                console.print()
                console.print(f"  [dim]🔒  {dm.sender}  →  {dm.recipient}[/]")
                for line in dm.content.splitlines():
                    console.print(f"  [dim]│  {line}[/]", markup=False)
                console.print()

    if not round3_dms:
        console.print("  [dim]No private messages exchanged.[/]")

    # ── ROUND 4: CROSS-DEBATE II (sequential, streaming) ──────────────────
    console.print()
    console.rule(Text("  ROUND 4  ·  CROSS-DEBATE II  ", style="bold yellow"), style="yellow")

    round4_responses: list[AgentResponse] = []
    for agent in agents:
        response, dm = await _agent_cross_debate(agent, session, 4, round4_responses)
        round4_responses.append(response)
        if dm:
            deliver_dm(dm, session)
            if session.show_dm_indicators:
                _print_dm_indicator(dm)

    session.rounds.append(round4_responses)

    # ── EACH AGENT PROPOSES A RESOLUTION ───────────────────────────────────
    console.print()
    console.rule(
        Text("  PROPOSE RESOLUTIONS  ", style="bold white on dark_magenta"),
        style="magenta",
    )
    console.print()

    for agent in agents:
        resolution = await _agent_propose_resolution(agent, session)
        session.resolutions[agent.name] = resolution
        console.print(f"  [{agent.rich_color}]{agent.name}[/]:")
        console.print(Panel(resolution, border_style="dim", padding=(0, 2)))
        console.print()

    # ── VOTE FOR ONE RESOLUTION (with tie-breaker loop) ──────────────────────
    MAX_TIEBREAKER_ROUNDS = 5
    active_resolutions = list(session.resolutions.keys())
    tiebreaker_round = 5

    while True:
        console.rule(
            Text(
                "  VOTE  ·  Pick one resolution  "
                + ("(tie-breaker)" if len(active_resolutions) < len(session.resolutions) else ""),
                style="bold yellow",
            ),
            style="yellow",
        )
        console.print()

        resolutions_in_play = [(p, session.resolutions[p]) for p in active_resolutions]
        votes: dict[str, str] = {}

        for voter in agents:
            voted_for = await _agent_vote_for_one_resolution(
                voter, session, resolutions_in_play
            )
            if voted_for:
                votes[voter.name] = voted_for
                console.print(
                    f"  [{voter.rich_color}]{voter.name}[/]: [bold]{voted_for}[/]"
                )
            else:
                console.print(
                    f"  [{voter.rich_color}]{voter.name}[/]: [dim](invalid vote, skipped)[/]"
                )

        session.vote_rounds.append(votes)
        counts = _compute_vote_counts(votes)
        winners = _get_tied_winners(counts)

        for p, c in sorted(counts.items(), key=lambda x: -x[1]):
            console.print(f"  [dim]→ {p}: {c} vote(s)[/]")
        console.print()

        if len(winners) == 1:
            break

        # No valid votes: keep current set and run tie-breaker
        if not winners:
            winners = active_resolutions

        # Tie: run tie-breaker debate
        if tiebreaker_round - 5 >= MAX_TIEBREAKER_ROUNDS:
            console.print(
                "[dim]Max tie-breaker rounds reached. Picking first tied resolution.[/]"
            )
            break

        active_resolutions = winners
        console.rule(
            Text(f"  TIE-BREAKER  ·  Debate round {tiebreaker_round - 4}  ", style="bold magenta"),
            style="magenta",
        )
        console.print(
            f"\n[dim]Resolutions still in contention: {', '.join(active_resolutions)}[/]\n"
        )

        tiebreaker_responses: list[AgentResponse] = []
        for agent in agents:
            response = await _agent_tiebreaker_debate(
                agent, session, tiebreaker_round, active_resolutions, tiebreaker_responses
            )
            tiebreaker_responses.append(response)
        session.rounds.append(tiebreaker_responses)
        tiebreaker_round += 1

    # ── TOP ANSWER + MODERATOR COMPARISON ───────────────────────────────────
    top3 = _get_top3_resolutions(session)

    # Moderator analysis
    console.print()
    console.rule(
        Text("  MODERATOR ANALYSIS  ", style="bold white on dark_green"),
        style="green",
    )
    console.print("\n[dim]Moderator reviewing top resolutions…[/]\n")
    report = await _moderator_pros_cons(
        question=session.question,
        top3=top3,
        agents=agents,
        model=session.model,
    )

    _render_top3_output(report, agents)
    console.rule(Text("  SESSION COMPLETE  ", style="bold white on dark_blue"), style="blue")
    console.print()


def _render_top3_output(report: ModeratorReport, agents: list[Agent]) -> None:
    """Render the Top Answer section and the 3-way comparison table."""
    from rich.table import Table

    if not report.analyses:
        return

    agent_by_name: dict[str, Agent] = {a.name: a for a in agents}

    # ── TOP ANSWER ────────────────────────────────────────────────────────
    console.rule(Text("  COUNCIL CONSENSUS  ", style="bold white on dark_blue"), style="blue")
    console.print()

    top = report.analyses[0]
    winner_agent = agent_by_name.get(top.agent_name)
    winner_color = winner_agent.rich_color if winner_agent else "bold green"
    console.print(
        Panel(
            top.resolution,
            title=(
                f"[bold green]#1 Resolution[/]  "
                f"[{winner_color}]{top.agent_name}[/]  [dim]· {top.agent_role}[/]"
            ),
            border_style="green",
            padding=(1, 2),
        )
    )
    console.print()

    # ── COMPARISON TABLE ──────────────────────────────────────────────────
    console.rule(Text("  TOP 3 COMPARISON  ", style="bold white on dark_magenta"), style="magenta")
    console.print()

    table = Table(show_header=True, header_style="bold magenta", expand=True, show_lines=True)
    table.add_column("Rank", style="bold", justify="center", width=6)
    table.add_column("Agent", style="bold cyan", min_width=14)
    table.add_column("Summary", min_width=24)
    table.add_column("Pros", style="green", min_width=28)
    table.add_column("Cons", style="red", min_width=28)

    for analysis in report.analyses:
        rank_label = f"#{analysis.rank}"
        pros_text = "\n".join(f"• {p}" for p in analysis.pros)
        cons_text = "\n".join(f"• {c}" for c in analysis.cons)
        table.add_row(
            rank_label,
            f"{analysis.agent_name}\n[dim]{analysis.agent_role}[/]",
            analysis.summary,
            pros_text,
            cons_text,
        )

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def list_agents(
    config_path: Path,
    personality_mode: PersonalityMode | None = None,
    generated_data: list[dict] | None = None,
) -> None:
    base_agents, _ = load_config(config_path)

    if personality_mode is None:
        agents = _resolve_default_agents(base_agents, generated_data)
    elif personality_mode == PersonalityMode.CANNED:
        agents = _dicts_to_agents(get_canned_personalities())
    elif personality_mode == PersonalityMode.GENERATED:
        agent_dicts = build_agent_panel(
            PersonalityMode.GENERATED,
            base_agents=[],
            generated_data=generated_data,
        )
        agents = _dicts_to_agents(agent_dicts)
    else:
        agent_dicts = build_agent_panel(
            personality_mode,
            base_agents=[a.__dict__ for a in base_agents],
        )
        agents = _dicts_to_agents(agent_dicts)
    console.print()
    console.print(Panel("[bold]Configured Agents[/]", border_style="blue"))
    for a in agents:
        role_str = a.role
        if a.job_role:
            role_str += f"  [{a.job_role.value}]"
        console.print(f"  [{a.rich_color}]▸ {a.name}[/]  [dim]{role_str}[/]")
    console.print()


# ---------------------------------------------------------------------------
# DM Mode — user ↔ single agent 1-on-1 (Feature 4)
# ---------------------------------------------------------------------------

_USER_DM_SYSTEM_SUFFIX = (
    "\n\nYou are currently in a PRIVATE DIRECT MESSAGE conversation with the user. "
    "This is outside the main council debate. Respond directly and personally as "
    "yourself. Be candid, thoughtful, and in-character. Keep responses focused and "
    "conversational (100-200 words unless the topic demands more)."
)

_USER_DM_INVITE_SYSTEM = (
    "\n\nYou are in a PRIVATE GROUP CHAT. Respond naturally in the conversation, "
    "staying in character. Keep responses concise and conversational."
)


async def _dm_agent_response(
    agent: Agent,
    history: list[dict],
    model: str,
) -> str:
    """Get a single agent response in a DM conversation."""
    system_prompt = agent.system_prompt + _USER_DM_SYSTEM_SUFFIX
    input_msgs = [{"role": "system", "content": system_prompt}] + history
    return (await api_call(input_msgs, max_tokens=512, model=model)).strip()


async def _group_chat_response(
    agents: list[Agent],
    history: list[dict],
    model: str,
) -> list[tuple[Agent, str]]:
    """Get responses from all agents in a group chat round (async parallel)."""

    async def _one(agent: Agent) -> tuple[Agent, str]:
        system_prompt = agent.system_prompt + _USER_DM_INVITE_SYSTEM
        input_msgs = [{"role": "system", "content": system_prompt}] + history
        text = (await api_call(input_msgs, max_tokens=300, model=agent.model or model)).strip()
        return agent, text

    results = await asyncio.gather(*[_one(a) for a in agents])
    return list(results)


async def run_dm_session(
    agent_name: str,
    config_path: Path,
    personality_mode: PersonalityMode | None = None,
    guardrails_enabled: bool = True,
    generated_data: list[dict] | None = None,
) -> None:
    """
    Run a private 1-on-1 DM session between the user and a single named agent.

    The user can invite additional agents mid-session by typing:
      /invite <agent name>

    Type 'quit' / 'exit' / 'q' to end the session.
    """
    base_agents, settings = load_config(config_path)
    default_model = settings.get("model", MODEL)

    # Build agent pool according to personality mode
    if personality_mode is not None:
        if personality_mode == PersonalityMode.GENERATED:
            agent_dicts = build_agent_panel(
                personality_mode,
                base_agents=[],
                generated_data=generated_data,
            )
        else:
            agent_dicts = build_agent_panel(
                personality_mode,
                base_agents=[a.__dict__ for a in base_agents],
            )
        all_agents = _dicts_to_agents(agent_dicts)
    else:
        all_agents = _resolve_default_agents(base_agents, generated_data)

    # Find the primary agent by name (case-insensitive, partial match)
    primary: Agent | None = None
    for a in all_agents:
        if agent_name.lower() in a.name.lower() or a.name.lower() in agent_name.lower():
            primary = a
            break

    if primary is None:
        console.print(
            Panel(
                f"[bold red]Agent '{agent_name}' not found.[/]\n\n"
                f"Available agents: {', '.join(a.name for a in all_agents)}",
                title="DM Error",
                border_style="red",
            )
        )
        return

    active_agents: list[Agent] = [primary]
    history: list[dict] = []
    is_group = False

    console.print()
    console.print(
        Panel(
            f"[bold]Private DM with {primary.name}[/]\n"
            f"[dim]{primary.role}[/]\n\n"
            "[dim]Type your message. "
            "Use [bold]/invite <name>[/] to add an agent. "
            "Type [bold]quit[/] to exit.[/]",
            border_style="blue",
            title="[bold blue]DM Mode[/]",
            padding=(1, 2),
        )
    )

    guardrails = Guardrails() if guardrails_enabled else None

    while True:
        console.print()
        try:
            user_input = console.input("[bold green]You >[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting DM.[/]")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Exiting DM.[/]")
            break

        if not user_input:
            continue

        # /invite command — add agent to group chat (Feature 4: Invite)
        if user_input.lower().startswith("/invite "):
            invite_name = user_input[8:].strip()
            invited: Agent | None = None
            for a in all_agents:
                if invite_name.lower() in a.name.lower() or a.name.lower() in invite_name.lower():
                    invited = a
                    break
            if invited is None:
                console.print(f"  [dim]Agent '{invite_name}' not found.[/]")
                continue
            if any(a.name == invited.name for a in active_agents):
                console.print(f"  [dim]{invited.name} is already in this chat.[/]")
                continue
            active_agents.append(invited)
            is_group = True
            console.print(
                f"  [dim]📨 {invited.name} has been invited to the conversation.[/]"
            )
            history.append({
                "role": "user",
                "content": f"[System: {invited.name} has joined the conversation.]",
            })
            continue

        # Guardrails check on user message
        if guardrails is not None:
            gr = guardrails.screen(user_input)
            if gr.blocked:
                console.print(
                    Panel(gr.summary(), title="[bold red]🚫 Message Blocked[/]", border_style="red")
                )
                continue

        history.append({"role": "user", "content": user_input})

        if is_group or len(active_agents) > 1:
            # Group chat — all active agents respond
            responses = await _group_chat_response(active_agents, history, default_model)
            group_content_parts = []
            for agent, text in responses:
                console.print()
                console.rule(Text(f"  {agent.name}  ·  {agent.role}  ", style=agent.rich_color))
                console.print()
                console.print(text, markup=False)
                console.print()
                group_content_parts.append(f"{agent.name}: {text}")
            # Append all agent responses as a single assistant turn
            history.append({
                "role": "assistant",
                "content": "\n\n".join(group_content_parts),
            })
        else:
            # 1-on-1 DM
            console.print()
            console.rule(Text(f"  {primary.name}  ·  {primary.role}  ", style=primary.rich_color))
            console.print()
            response = await _dm_agent_response(
                primary, history, primary.model or default_model
            )
            console.print(response, markup=False)
            console.print()
            history.append({"role": "assistant", "content": response})


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def interactive_mode(
    config_path: Path,
    personality_mode: PersonalityMode | None = None,
    guardrails_enabled: bool = True,
    generated_data: list[dict] | None = None,
) -> None:
    console.print()
    mode_label = f"  Mode: [bold]{personality_mode.value}[/]" if personality_mode else ""
    console.print(
        Panel(
            "[bold]Council — Interactive Mode[/]\n"
            "[dim]Type your question and press Enter. Type [bold]quit[/] to exit.[/]"
            + (f"\n{mode_label}" if mode_label else ""),
            border_style="blue",
        )
    )
    while True:
        console.print()
        try:
            question = console.input("[bold blue]Council >[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting.[/]")
            break

        if question.lower() in ("quit", "exit", "q"):
            console.print("[dim]Exiting.[/]")
            break
        if not question:
            continue

        asyncio.run(
            run_council(
                question,
                config_path,
                personality_mode=personality_mode,
                guardrails_enabled=guardrails_enabled,
                generated_data=generated_data,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Council — Multi-agent expert debate system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python council.py "Is this JWT auth design secure?"
              python council.py "Should I use PostgreSQL or MongoDB?"
              python council.py --config my_panel.yaml "What tech stack should I choose?"
              python council.py --mode canned "Should we raise prices?"
              python council.py --mode dynamic "What is the future of AI regulation?"
              python council.py --mode hybrid "Should we go open-source?"
              python council.py --mode generated --people people.json "What should we build?"
                            python council.py --build-persona
                            python council.py --set-active "Kavin" false
              python council.py --dm "The Skeptic" --mode canned
              python council.py --list-agents
              python council.py --no-guardrails "My question"
            """
        ),
    )
    parser.add_argument("question", nargs="?", help="Question to put to the expert panel")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        metavar="FILE",
        help="Path to agents YAML config (default: agents.yaml)",
    )
    parser.add_argument("--list-agents", action="store_true", help="List configured agents")
    parser.add_argument(
        "--mode",
        choices=["canned", "dynamic", "hybrid", "generated"],
        default=None,
        metavar="MODE",
        help=(
            "Personality mode: canned (5 predefined), dynamic (LLM-generated), "
            "hybrid (mix), generated (clone personas from a JSON file, see --people). "
            "Default: use agents.yaml."
        ),
    )
    parser.add_argument(
        "--people",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "Path to a JSON file for --mode generated. The file must contain a list "
            'of objects with at minimum {"name": "...", "data": "..."} keys. '
            "data should be publicly available text describing the person. "
            f"Default when omitted: {DEFAULT_GENERATED_PEOPLE_FILE}"
        ),
    )
    parser.add_argument(
        "--build-persona",
        action="store_true",
        help=(
            "Launch interactive branched questionnaire, synthesize a comprehensive "
            f"profile with {PROFILE_BUILDER_MODEL}, and save/update a generated persona JSON entry."
        ),
    )
    parser.add_argument(
        "--set-active",
        nargs=2,
        metavar=("NAME", "STATE"),
        help="Set generated persona active state by name. STATE must be true or false.",
    )
    parser.add_argument(
        "--dm",
        metavar="AGENT_NAME",
        default=None,
        help="Start a private 1-on-1 DM session with the named agent (Feature 4).",
    )
    guardrail_group = parser.add_mutually_exclusive_group()
    guardrail_group.add_argument(
        "--guardrails",
        dest="guardrails",
        action="store_true",
        default=True,
        help="Enable input guardrails (default: on).",
    )
    guardrail_group.add_argument(
        "--no-guardrails",
        dest="guardrails",
        action="store_false",
        help="Disable input guardrails.",
    )

    args = parser.parse_args()

    # Resolve personality mode
    pmode: PersonalityMode | None = None
    if args.mode:
        pmode = PersonalityMode(args.mode)

    people_path = _resolve_people_path(args.people)

    if args.build_persona:
        asyncio.run(run_persona_questionnaire(people_path))
        return

    if args.set_active:
        name, state_raw = args.set_active
        state = state_raw.strip().lower()
        if state not in {"true", "false"}:
            console.print(
                Panel(
                    "[bold red]Invalid STATE for --set-active.[/] Use true or false.",
                    title="Argument Error",
                    border_style="red",
                )
            )
            sys.exit(1)
        try:
            updated = set_persona_active(people_path, name, active=(state == "true"))
        except ValueError as exc:
            console.print(Panel(f"[bold red]{exc}[/]", title="File Error", border_style="red"))
            sys.exit(1)
        if not updated:
            console.print(
                Panel(
                    f"[bold yellow]No persona named '{name}' found in {people_path}.[/]",
                    title="No Match",
                    border_style="yellow",
                )
            )
            sys.exit(1)
        console.print(
            Panel(
                f"[bold green]Updated active state.[/]\nName: {name}\nActive: {state}\nFile: {people_path}",
                title="Persona Updated",
                border_style="green",
            )
        )
        return

    # Load generated_data for generated mode and generated-mode list/DM paths.
    generated_data: list[dict] | None = None
    should_load_people = (
        bool(args.people)
        or pmode == PersonalityMode.GENERATED
        or pmode is None
    )
    if should_load_people:
        try:
            generated_data = load_generated_people(people_path)
        except ValueError as exc:
            if pmode is None and not args.people:
                console.print(
                    Panel(
                        f"[bold yellow]Could not load default generated personas.[/]\n{exc}\n\n"
                        "Continuing without generated personas.",
                        title="Generated Personas Warning",
                        border_style="yellow",
                    )
                )
                generated_data = None
            else:
                console.print(
                    Panel(
                        f"[bold red]{exc}[/]",
                        title="File Error",
                        border_style="red",
                    )
                )
                sys.exit(1)

    if pmode == PersonalityMode.GENERATED and not generated_data:
        console.print(
            Panel(
                "[bold yellow]Generated mode has no personas loaded.[/]\n"
                f"Expected file: {people_path}\n"
                "Run --build-persona to create one.",
                title="Generated Personas Missing",
                border_style="yellow",
            )
        )
        sys.exit(1)

    if args.list_agents:
        list_agents(args.config, pmode, generated_data=generated_data)
        return

    # DM Mode (Feature 4)
    if args.dm:
        asyncio.run(
            run_dm_session(
                args.dm,
                args.config,
                personality_mode=pmode,
                guardrails_enabled=args.guardrails,
                generated_data=generated_data,
            )
        )
        return

    if args.question:
        asyncio.run(
            run_council(
                args.question,
                args.config,
                personality_mode=pmode,
                guardrails_enabled=args.guardrails,
                generated_data=generated_data,
            )
        )
    else:
        interactive_mode(
            args.config,
            personality_mode=pmode,
            guardrails_enabled=args.guardrails,
            generated_data=generated_data,
        )


if __name__ == "__main__":
    main()
