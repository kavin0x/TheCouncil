"""TheCouncil features module."""

from council.features.guardrails import (
    Guardrails,
    GuardrailBackend,
    GuardrailResult,
    GuardrailViolation,
    ViolationType,
    RegexGuardrailBackend,
    LLMGuardrailBackend,
)
from council.features.personalities import (
    PersonalityMode,
    JobRole,
    build_agent_panel,
    get_canned_personalities,
    generate_mbti_personality,
    parse_dynamic_agents,
    DYNAMIC_GENERATION_PROMPT,
)
from council.features.sandbox import (
    run_sandbox_task,
    SandboxDisabledError,
)

__all__ = [
    # Guardrails
    "Guardrails",
    "GuardrailBackend",
    "GuardrailResult",
    "GuardrailViolation",
    "ViolationType",
    "RegexGuardrailBackend",
    "LLMGuardrailBackend",
    # Personalities
    "PersonalityMode",
    "JobRole",
    "build_agent_panel",
    "get_canned_personalities",
    "generate_mbti_personality",
    "parse_dynamic_agents",
    "DYNAMIC_GENERATION_PROMPT",
    # Sandbox
    "run_sandbox_task",
    "SandboxDisabledError",
]
