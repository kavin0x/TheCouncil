"""
Subscription tiers and Stripe integration helpers for TheCouncil.

Tier structure (monthly billing):
  Starter    $10  — casual use, basic council runs
  Pro        $50  — heavier use, export, history
  Business  $100  — API access, priority processing
  Enterprise $200 — MCP/plugin integrations, maximum usage (budget-safe ceiling)

Feature gating:
  - MCP and plugin/tooling integrations require Business or Enterprise.
  - API token access requires Pro or above.
  - Export (JSON/Markdown) requires Pro or above.
  - Session history requires Pro or above.

Usage limits are set conservatively so that at full utilization the token cost
for the highest tier remains within a sustainable operational budget.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------


class TierName(str, Enum):
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class UsageLimits:
    """Monthly usage limits for a subscription tier."""

    # Maximum council runs per calendar month
    runs_per_month: int
    # Maximum agents per council run
    max_agents: int
    # Maximum debate rounds per run (0 = use session default)
    max_rounds: int
    # Maximum input tokens per run
    max_input_tokens: int
    # Whether async / queued runs are allowed (vs. synchronous only)
    async_runs: bool
    # Export to JSON / Markdown
    export_enabled: bool
    # Session history retention (days; 0 = no retention)
    history_days: int
    # API token access
    api_access: bool
    # MCP and plugin/tooling integrations
    mcp_enabled: bool
    # Plugin/third-party integration adapters
    plugins_enabled: bool


TIER_LIMITS: dict[TierName, UsageLimits] = {
    TierName.STARTER: UsageLimits(
        runs_per_month=20,
        max_agents=5,
        max_rounds=4,
        max_input_tokens=2_000,
        async_runs=False,
        export_enabled=False,
        history_days=0,
        api_access=False,
        mcp_enabled=False,
        plugins_enabled=False,
    ),
    TierName.PRO: UsageLimits(
        runs_per_month=100,
        max_agents=8,
        max_rounds=6,
        max_input_tokens=8_000,
        async_runs=True,
        export_enabled=True,
        history_days=30,
        api_access=True,
        mcp_enabled=False,
        plugins_enabled=False,
    ),
    TierName.BUSINESS: UsageLimits(
        runs_per_month=500,
        max_agents=12,
        max_rounds=8,
        max_input_tokens=24_000,
        async_runs=True,
        export_enabled=True,
        history_days=90,
        api_access=True,
        mcp_enabled=True,
        plugins_enabled=True,
    ),
    TierName.ENTERPRISE: UsageLimits(
        # Ceiling set so peak monthly token cost stays within operational budget.
        # Estimated: 2000 runs × 12 agents × 8 rounds × ~1500 tokens/msg ≈ 288M tokens.
        # At ~$5/1M tokens that is ~$1 440/month in model cost, well within a
        # $200/seat revenue stream at expected concurrency levels.
        runs_per_month=2_000,
        max_agents=15,
        max_rounds=8,
        max_input_tokens=32_000,
        async_runs=True,
        export_enabled=True,
        history_days=365,
        api_access=True,
        mcp_enabled=True,
        plugins_enabled=True,
    ),
}


@dataclass(frozen=True)
class SubscriptionTier:
    """Full descriptor for a single subscription tier."""

    name: TierName
    display_name: str
    price_usd_monthly: int  # in whole dollars
    stripe_price_id_env_var: str  # env-var that holds the Stripe Price ID
    description: str
    limits: UsageLimits
    features: list[str] = field(default_factory=list)

    @property
    def stripe_price_id(self) -> str | None:
        """Return the Stripe Price ID from the environment, or None if not configured."""
        return os.getenv(self.stripe_price_id_env_var)


TIERS: dict[TierName, SubscriptionTier] = {
    TierName.STARTER: SubscriptionTier(
        name=TierName.STARTER,
        display_name="Starter",
        price_usd_monthly=10,
        stripe_price_id_env_var="STRIPE_PRICE_ID_STARTER",
        description="Perfect for casual use and exploration.",
        limits=TIER_LIMITS[TierName.STARTER],
        features=[
            "20 council runs / month",
            "Up to 5 agents per run",
            "4 debate rounds",
            "Web UI access",
        ],
    ),
    TierName.PRO: SubscriptionTier(
        name=TierName.PRO,
        display_name="Pro",
        price_usd_monthly=50,
        stripe_price_id_env_var="STRIPE_PRICE_ID_PRO",
        description="For power users who need more capacity and exports.",
        limits=TIER_LIMITS[TierName.PRO],
        features=[
            "100 council runs / month",
            "Up to 8 agents per run",
            "6 debate rounds",
            "JSON / Markdown export",
            "30-day session history",
            "API token access",
        ],
    ),
    TierName.BUSINESS: SubscriptionTier(
        name=TierName.BUSINESS,
        display_name="Business",
        price_usd_monthly=100,
        stripe_price_id_env_var="STRIPE_PRICE_ID_BUSINESS",
        description="For teams and API integrations with MCP tooling.",
        limits=TIER_LIMITS[TierName.BUSINESS],
        features=[
            "500 council runs / month",
            "Up to 12 agents per run",
            "8 debate rounds",
            "JSON / Markdown export",
            "90-day session history",
            "API token access",
            "MCP integrations",
            "Plugin/tooling adapters",
            "Priority processing queue",
        ],
    ),
    TierName.ENTERPRISE: SubscriptionTier(
        name=TierName.ENTERPRISE,
        display_name="Enterprise",
        price_usd_monthly=200,
        stripe_price_id_env_var="STRIPE_PRICE_ID_ENTERPRISE",
        description="Maximum capacity for heavy workloads with full feature access.",
        limits=TIER_LIMITS[TierName.ENTERPRISE],
        features=[
            "2 000 council runs / month",
            "Up to 15 agents per run",
            "8 debate rounds",
            "JSON / Markdown export",
            "1-year session history",
            "API token access",
            "MCP integrations",
            "Plugin/tooling adapters",
            "Priority processing queue",
            "SLA support",
        ],
    ),
}

# Ordered list of tiers from lowest to highest
TIER_ORDER: list[TierName] = [
    TierName.STARTER,
    TierName.PRO,
    TierName.BUSINESS,
    TierName.ENTERPRISE,
]


# ---------------------------------------------------------------------------
# Tier resolution helpers
# ---------------------------------------------------------------------------


def get_tier(tier_name: str | TierName) -> SubscriptionTier:
    """Return a SubscriptionTier by name, raising ValueError for unknown names."""
    key = TierName(tier_name) if isinstance(tier_name, str) else tier_name
    if key not in TIERS:
        raise ValueError(f"Unknown tier: {tier_name!r}")
    return TIERS[key]


def tier_allows_feature(tier_name: str | TierName, feature: str) -> bool:
    """Return True if the given tier has access to *feature*.

    Supported feature keys:
      "mcp", "plugins", "api", "export", "history", "async_runs"
    """
    limits = get_tier(tier_name).limits
    feature_map: dict[str, bool] = {
        "mcp": limits.mcp_enabled,
        "plugins": limits.plugins_enabled,
        "api": limits.api_access,
        "export": limits.export_enabled,
        "history": limits.history_days > 0,
        "async_runs": limits.async_runs,
    }
    if feature not in feature_map:
        raise ValueError(
            f"Unknown feature key {feature!r}. "
            f"Valid keys: {sorted(feature_map)}"
        )
    return feature_map[feature]


def is_within_run_limit(tier_name: str | TierName, current_run_count: int) -> bool:
    """Return True if the subscriber has not yet exhausted their monthly run quota."""
    limits = get_tier(tier_name).limits
    return current_run_count < limits.runs_per_month


# ---------------------------------------------------------------------------
# Stripe checkout / webhook helpers (thin wrappers; real calls require stripe-python)
# ---------------------------------------------------------------------------


def build_checkout_session_params(
    tier_name: str | TierName,
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    """Return a dict of params suitable for passing to ``stripe.checkout.Session.create``.

    The caller is responsible for importing ``stripe`` and setting
    ``stripe.api_key = os.getenv("STRIPE_SECRET_KEY")`` before calling
    ``stripe.checkout.Session.create(**params)``.
    """
    tier = get_tier(tier_name)
    price_id = tier.stripe_price_id
    if not price_id:
        raise RuntimeError(
            f"Stripe Price ID for tier '{tier.name.value}' is not configured. "
            f"Set the {tier.stripe_price_id_env_var} environment variable."
        )
    return {
        "mode": "subscription",
        "customer_email": customer_email,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"tier": tier.name.value},
    }


def parse_webhook_event(payload: bytes, sig_header: str, webhook_secret: str) -> dict[str, Any]:
    """Verify and parse a Stripe webhook event payload.

    Returns the parsed event dict on success.
    Raises ``ValueError`` if the signature is invalid or the payload cannot be parsed.

    The caller must have ``stripe`` installed; this function imports it lazily.
    """
    try:
        import stripe  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "The 'stripe' package is required for webhook verification. "
            "Install it with: pip install stripe"
        ) from exc

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError as exc:  # type: ignore[attr-defined]
        raise ValueError(f"Stripe webhook signature verification failed: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Could not parse Stripe webhook payload: {exc}") from exc

    return dict(event)


def resolve_tier_from_webhook(event: dict[str, Any]) -> TierName | None:
    """Extract the TierName from a ``checkout.session.completed`` webhook event.

    Returns None when the tier cannot be determined (e.g. wrong event type).
    """
    if event.get("type") != "checkout.session.completed":
        return None
    metadata = (event.get("data") or {}).get("object", {}).get("metadata") or {}
    raw_tier = metadata.get("tier")
    if not raw_tier:
        return None
    try:
        return TierName(raw_tier)
    except ValueError:
        return None
