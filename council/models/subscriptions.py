"""
Subscription tiers and Stripe integration helpers for TheCouncil SaaS.

Target commercial model:
  Trial (14 days), Basic ($10), Pro ($20), Ultra ($200), Enterprise ($25+/seat).

Notes:
  - "Unlimited" tiers are implemented as high, budget-safe caps plus fair-use flags.
  - Trial is a non-billable entitlement tier; checkout should start on a paid tier with
    trial days applied in Stripe subscription_data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


DEFAULT_TRIAL_DAYS = 14


class TierName(str, Enum):
    TRIAL = "trial"
    BASIC = "basic"
    PRO = "pro"
    ULTRA = "ultra"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class UsageLimits:
    """Monthly usage limits and feature flags for a subscription tier."""

    runs_per_month: int
    max_agents: int
    max_rounds: int
    max_input_tokens: int
    async_runs: bool
    export_enabled: bool
    history_days: int
    api_access: bool
    mcp_enabled: bool
    plugins_enabled: bool

    # SaaS-specific entitlements
    max_saved_personas: int | None
    ide_plugins_enabled: bool
    custom_mcp_enabled: bool
    web_search_enabled: bool
    computer_use_enabled: bool
    cua_enabled: bool
    sso_enabled: bool
    centralized_billing_enabled: bool
    fair_use_policy_required: bool


TIER_LIMITS: dict[TierName, UsageLimits] = {
    TierName.TRIAL: UsageLimits(
        runs_per_month=60,
        max_agents=8,
        max_rounds=6,
        max_input_tokens=8_000,
        async_runs=True,
        export_enabled=True,
        history_days=14,
        api_access=True,
        mcp_enabled=True,
        plugins_enabled=True,
        max_saved_personas=3,
        ide_plugins_enabled=True,
        custom_mcp_enabled=False,
        web_search_enabled=False,
        computer_use_enabled=False,
        cua_enabled=False,
        sso_enabled=False,
        centralized_billing_enabled=False,
        fair_use_policy_required=True,
    ),
    TierName.BASIC: UsageLimits(
        runs_per_month=100,
        max_agents=6,
        max_rounds=4,
        max_input_tokens=4_000,
        async_runs=False,
        export_enabled=False,
        history_days=7,
        api_access=True,
        mcp_enabled=False,
        plugins_enabled=False,
        max_saved_personas=1,
        ide_plugins_enabled=False,
        custom_mcp_enabled=False,
        web_search_enabled=False,
        computer_use_enabled=False,
        cua_enabled=False,
        sso_enabled=False,
        centralized_billing_enabled=False,
        fair_use_policy_required=False,
    ),
    TierName.PRO: UsageLimits(
        runs_per_month=500,
        max_agents=10,
        max_rounds=8,
        max_input_tokens=12_000,
        async_runs=True,
        export_enabled=True,
        history_days=30,
        api_access=True,
        mcp_enabled=True,
        plugins_enabled=True,
        max_saved_personas=10,
        ide_plugins_enabled=True,
        custom_mcp_enabled=True,
        web_search_enabled=True,
        computer_use_enabled=False,
        cua_enabled=False,
        sso_enabled=False,
        centralized_billing_enabled=False,
        fair_use_policy_required=False,
    ),
    TierName.ULTRA: UsageLimits(
        runs_per_month=10_000,
        max_agents=15,
        max_rounds=10,
        max_input_tokens=32_000,
        async_runs=True,
        export_enabled=True,
        history_days=180,
        api_access=True,
        mcp_enabled=True,
        plugins_enabled=True,
        max_saved_personas=None,
        ide_plugins_enabled=True,
        custom_mcp_enabled=True,
        web_search_enabled=True,
        computer_use_enabled=True,
        cua_enabled=True,
        sso_enabled=False,
        centralized_billing_enabled=False,
        fair_use_policy_required=True,
    ),
    TierName.ENTERPRISE: UsageLimits(
        runs_per_month=25_000,
        max_agents=20,
        max_rounds=12,
        max_input_tokens=64_000,
        async_runs=True,
        export_enabled=True,
        history_days=365,
        api_access=True,
        mcp_enabled=True,
        plugins_enabled=True,
        max_saved_personas=None,
        ide_plugins_enabled=True,
        custom_mcp_enabled=True,
        web_search_enabled=True,
        computer_use_enabled=True,
        cua_enabled=True,
        sso_enabled=True,
        centralized_billing_enabled=True,
        fair_use_policy_required=True,
    ),
}


@dataclass(frozen=True)
class SubscriptionTier:
    name: TierName
    display_name: str
    price_usd_monthly: int
    stripe_price_id_env_var: str | None
    description: str
    limits: UsageLimits
    features: list[str] = field(default_factory=list)
    trial_days: int = 0

    @property
    def stripe_price_id(self) -> str | None:
        if not self.stripe_price_id_env_var:
            return None
        return os.getenv(self.stripe_price_id_env_var)


TIERS: dict[TierName, SubscriptionTier] = {
    TierName.TRIAL: SubscriptionTier(
        name=TierName.TRIAL,
        display_name="Trial",
        price_usd_monthly=0,
        stripe_price_id_env_var=None,
        description="14-day preview tier with capped usage and selected Pro features.",
        limits=TIER_LIMITS[TierName.TRIAL],
        features=[
            "14-day access window",
            "Run history and exports",
            "Limited saved personas",
            "IDE/MCP preview access",
        ],
        trial_days=DEFAULT_TRIAL_DAYS,
    ),
    TierName.BASIC: SubscriptionTier(
        name=TierName.BASIC,
        display_name="Basic",
        price_usd_monthly=10,
        stripe_price_id_env_var="STRIPE_PRICE_ID_BASIC",
        description="Low-cost plan for light individual usage.",
        limits=TIER_LIMITS[TierName.BASIC],
        features=[
            "100 runs per month",
            "1 saved persona",
            "Web/API access",
        ],
    ),
    TierName.PRO: SubscriptionTier(
        name=TierName.PRO,
        display_name="Pro",
        price_usd_monthly=20,
        stripe_price_id_env_var="STRIPE_PRICE_ID_PRO",
        description="Higher limits with IDE integrations and custom MCP support.",
        limits=TIER_LIMITS[TierName.PRO],
        features=[
            "500 runs per month",
            "10 saved personas",
            "MCP + IDE integrations",
            "Custom MCP support",
        ],
    ),
    TierName.ULTRA: SubscriptionTier(
        name=TierName.ULTRA,
        display_name="Ultra",
        price_usd_monthly=200,
        stripe_price_id_env_var="STRIPE_PRICE_ID_ULTRA",
        description="High-capacity plan with sandboxed computer-use workflows.",
        limits=TIER_LIMITS[TierName.ULTRA],
        features=[
            "High fair-use monthly limits",
            "Unlimited saved personas",
            "Computer-use and CUA-enabled",
            "All Pro integrations",
        ],
    ),
    TierName.ENTERPRISE: SubscriptionTier(
        name=TierName.ENTERPRISE,
        display_name="Enterprise",
        price_usd_monthly=25,
        stripe_price_id_env_var="STRIPE_PRICE_ID_ENTERPRISE",
        description="Contracted seat-based plan with enterprise controls.",
        limits=TIER_LIMITS[TierName.ENTERPRISE],
        features=[
            "Configurable seat pricing",
            "Unlimited personas",
            "SSO and centralized billing",
            "Org-level integrations and controls",
        ],
    ),
}


TIER_ORDER: list[TierName] = [
    TierName.TRIAL,
    TierName.BASIC,
    TierName.PRO,
    TierName.ULTRA,
    TierName.ENTERPRISE,
]


def get_tier(tier_name: str | TierName) -> SubscriptionTier:
    key = TierName(tier_name) if isinstance(tier_name, str) else tier_name
    if key not in TIERS:
        raise ValueError(f"Unknown tier: {tier_name!r}")
    return TIERS[key]


def tier_allows_feature(tier_name: str | TierName, feature: str) -> bool:
    """Return True if the given tier has access to *feature*.

    Supported feature keys:
      "mcp", "plugins", "api", "export", "history", "async_runs",
      "ide_plugins", "custom_mcp", "web_search", "computer_use", "cua", "sso",
      "centralized_billing", "personas_unlimited"
    """
    limits = get_tier(tier_name).limits
    feature_map: dict[str, bool] = {
        "mcp": limits.mcp_enabled,
        "plugins": limits.plugins_enabled,
        "api": limits.api_access,
        "export": limits.export_enabled,
        "history": limits.history_days > 0,
        "async_runs": limits.async_runs,
        "ide_plugins": limits.ide_plugins_enabled,
        "custom_mcp": limits.custom_mcp_enabled,
        "web_search": limits.web_search_enabled,
        "computer_use": limits.computer_use_enabled,
        "cua": limits.cua_enabled,
        "sso": limits.sso_enabled,
        "centralized_billing": limits.centralized_billing_enabled,
        "personas_unlimited": limits.max_saved_personas is None,
    }
    if feature not in feature_map:
        raise ValueError(
            f"Unknown feature key {feature!r}. "
            f"Valid keys: {sorted(feature_map)}"
        )
    return feature_map[feature]


def is_within_run_limit(tier_name: str | TierName, current_run_count: int) -> bool:
    limits = get_tier(tier_name).limits
    return current_run_count < limits.runs_per_month


def get_trial_days() -> int:
    """Return configured trial days (defaults to 14)."""
    raw = os.getenv("TRIAL_PERIOD_DAYS", str(DEFAULT_TRIAL_DAYS)).strip()
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_TRIAL_DAYS
    return max(0, days)


def build_payment_link_params(
    tier_name: str | TierName,
    success_url: str,
    customer_email: str | None = None,
    apply_trial: bool = True,
) -> dict[str, Any]:
    """Return params suitable for ``stripe.PaymentLink.create``.

    Trial can be applied to paid tiers by setting subscription_data.trial_period_days.
    The Trial tier itself is non-billable and cannot generate a payment link.
    """
    tier = get_tier(tier_name)
    if tier.name is TierName.TRIAL:
        raise RuntimeError("Trial tier is non-billable and cannot create a payment link.")

    price_id = tier.stripe_price_id
    if not price_id:
        raise RuntimeError(
            f"Stripe Price ID for tier '{tier.name.value}' is not configured. "
            f"Set the {tier.stripe_price_id_env_var} environment variable."
        )

    metadata: dict[str, str] = {"tier": tier.name.value}
    if customer_email:
        metadata["customer_email_hint"] = customer_email

    subscription_data: dict[str, Any] = {"metadata": {"tier": tier.name.value}}
    trial_days = get_trial_days()
    if apply_trial and trial_days > 0:
        subscription_data["trial_period_days"] = trial_days

    return {
        "line_items": [{"price": price_id, "quantity": 1}],
        "metadata": metadata,
        "subscription_data": subscription_data,
        "after_completion": {
            "type": "redirect",
            "redirect": {"url": success_url},
        },
    }


def build_checkout_session_params(
    tier_name: str | TierName,
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    _ = cancel_url
    return build_payment_link_params(
        tier_name=tier_name,
        success_url=success_url,
        customer_email=customer_email,
    )


def parse_webhook_event(payload: bytes, sig_header: str, webhook_secret: str) -> dict[str, Any]:
    """Verify and parse a Stripe webhook event payload."""
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

    # Convert Stripe Event object to dict; handle type conversion safely
    result: dict[str, Any] = {}
    try:
        if hasattr(event, 'items'):
            result = dict(event.items())
        else:
            result = dict(event.__dict__)
    except (TypeError, AttributeError):
        pass
    return result


def resolve_tier_from_webhook(event: dict[str, Any]) -> TierName | None:
    """Extract TierName from common Stripe subscription lifecycle webhook payloads."""
    event_type = event.get("type")
    supported_types = {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
    }
    if event_type not in supported_types:
        return None

    obj = (event.get("data") or {}).get("object", {})

    # Checkout session metadata
    metadata = obj.get("metadata") or {}
    raw_tier = metadata.get("tier")

    # Subscription object metadata
    if not raw_tier:
        sub_meta = (obj.get("subscription_details") or {}).get("metadata") or {}
        raw_tier = sub_meta.get("tier")

    # Expanded subscription payload fallback
    if not raw_tier:
        sub_obj = obj.get("subscription") or {}
        if isinstance(sub_obj, dict):
            raw_tier = (sub_obj.get("metadata") or {}).get("tier")

    if not raw_tier:
        return None
    try:
        return TierName(raw_tier)
    except ValueError:
        return None
