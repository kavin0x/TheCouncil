"""TheCouncil — Multi-agent expert debate system."""

__version__ = "0.1.0"

# Core council debate engine
from council.core.council import (
    Agent,
    AgentResponse,
    DM,
    DebateSession,
    MODEL,
)

# Features
from council.features.guardrails import (
    Guardrails,
    GuardrailBackend,
    GuardrailResult,
    GuardrailViolation,
    ViolationType,
)
from council.features.personalities import (
    PersonalityMode,
    JobRole,
)
from council.features.sandbox import (
    run_sandbox_task,
    SandboxDisabledError,
)

# Models
from council.models.state import (
    Run,
    RunStatus,
    run_store,
    run_queue,
)
from council.models.subscriptions import (
    TierName,
    SubscriptionTier,
)

# API
from council.api.app import app as fastapi_app

__all__ = [
    # Version
    "__version__",
    # Core
    "Agent",
    "AgentResponse",
    "DM",
    "DebateSession",
    "MODEL",
    # Features
    "Guardrails",
    "GuardrailBackend",
    "GuardrailResult",
    "GuardrailViolation",
    "ViolationType",
    "PersonalityMode",
    "JobRole",
    "run_sandbox_task",
    "SandboxDisabledError",
    # Models
    "Run",
    "RunStatus",
    "run_store",
    "run_queue",
    "TierName",
    "SubscriptionTier",
    # API
    "fastapi_app",
]
