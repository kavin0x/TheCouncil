"""
Unit tests for subscriptions.py — tier definitions and feature gating.
"""

import os
import pytest

from subscriptions import (
    TierName,
    TIERS,
    TIER_ORDER,
    UsageLimits,
    SubscriptionTier,
    get_tier,
    tier_allows_feature,
    is_within_run_limit,
    build_checkout_session_params,
    resolve_tier_from_webhook,
)


# ---------------------------------------------------------------------------
# Tier catalog completeness
# ---------------------------------------------------------------------------


class TestTierCatalog:
    def test_all_four_tiers_defined(self):
        """Exactly four tiers are defined."""
        assert set(TIERS.keys()) == {
            TierName.STARTER,
            TierName.PRO,
            TierName.BUSINESS,
            TierName.ENTERPRISE,
        }

    def test_tier_order_is_ascending(self):
        """TIER_ORDER contains all tiers in ascending price order."""
        assert TIER_ORDER == [
            TierName.STARTER,
            TierName.PRO,
            TierName.BUSINESS,
            TierName.ENTERPRISE,
        ]
        prices = [TIERS[t].price_usd_monthly for t in TIER_ORDER]
        assert prices == sorted(prices), "Tiers must be in ascending price order"

    def test_each_tier_has_required_fields(self):
        for tier in TIERS.values():
            assert isinstance(tier, SubscriptionTier)
            assert tier.display_name
            assert tier.price_usd_monthly > 0
            assert tier.stripe_price_id_env_var
            assert tier.description
            assert isinstance(tier.limits, UsageLimits)
            assert len(tier.features) >= 1

    def test_prices_match_spec(self):
        """Tier prices must match the $10 / $50 / $100 / $200 specification."""
        assert TIERS[TierName.STARTER].price_usd_monthly == 10
        assert TIERS[TierName.PRO].price_usd_monthly == 50
        assert TIERS[TierName.BUSINESS].price_usd_monthly == 100
        assert TIERS[TierName.ENTERPRISE].price_usd_monthly == 200


# ---------------------------------------------------------------------------
# Usage limits ordering
# ---------------------------------------------------------------------------


class TestUsageLimitsOrdering:
    def test_runs_per_month_increases_with_tier(self):
        runs = [TIERS[t].limits.runs_per_month for t in TIER_ORDER]
        assert runs == sorted(runs)

    def test_max_agents_increases_with_tier(self):
        agents = [TIERS[t].limits.max_agents for t in TIER_ORDER]
        assert agents == sorted(agents)

    def test_input_tokens_increases_with_tier(self):
        tokens = [TIERS[t].limits.max_input_tokens for t in TIER_ORDER]
        assert tokens == sorted(tokens)

    def test_history_days_increases_with_tier(self):
        days = [TIERS[t].limits.history_days for t in TIER_ORDER]
        assert days == sorted(days)


# ---------------------------------------------------------------------------
# Feature gating: MCP / plugins only at Business+
# ---------------------------------------------------------------------------


class TestFeatureGating:
    def test_starter_no_mcp(self):
        assert not tier_allows_feature(TierName.STARTER, "mcp")

    def test_starter_no_plugins(self):
        assert not tier_allows_feature(TierName.STARTER, "plugins")

    def test_starter_no_api(self):
        assert not tier_allows_feature(TierName.STARTER, "api")

    def test_starter_no_export(self):
        assert not tier_allows_feature(TierName.STARTER, "export")

    def test_starter_no_history(self):
        assert not tier_allows_feature(TierName.STARTER, "history")

    def test_starter_no_async_runs(self):
        assert not tier_allows_feature(TierName.STARTER, "async_runs")

    def test_pro_has_api_access(self):
        assert tier_allows_feature(TierName.PRO, "api")

    def test_pro_has_export(self):
        assert tier_allows_feature(TierName.PRO, "export")

    def test_pro_has_history(self):
        assert tier_allows_feature(TierName.PRO, "history")

    def test_pro_no_mcp(self):
        assert not tier_allows_feature(TierName.PRO, "mcp")

    def test_pro_no_plugins(self):
        assert not tier_allows_feature(TierName.PRO, "plugins")

    def test_business_has_mcp(self):
        assert tier_allows_feature(TierName.BUSINESS, "mcp")

    def test_business_has_plugins(self):
        assert tier_allows_feature(TierName.BUSINESS, "plugins")

    def test_enterprise_has_all_features(self):
        for feature in ("mcp", "plugins", "api", "export", "history", "async_runs"):
            assert tier_allows_feature(TierName.ENTERPRISE, feature), (
                f"Enterprise should allow feature '{feature}'"
            )

    def test_string_tier_name_accepted(self):
        """tier_allows_feature accepts a plain string as the tier name."""
        assert not tier_allows_feature("starter", "mcp")
        assert tier_allows_feature("enterprise", "mcp")

    def test_unknown_feature_raises(self):
        with pytest.raises(ValueError, match="Unknown feature key"):
            tier_allows_feature(TierName.ENTERPRISE, "unknown_feature")

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError):
            tier_allows_feature("diamond", "mcp")


# ---------------------------------------------------------------------------
# get_tier helper
# ---------------------------------------------------------------------------


class TestGetTier:
    def test_returns_correct_tier_by_enum(self):
        tier = get_tier(TierName.PRO)
        assert tier.name is TierName.PRO

    def test_returns_correct_tier_by_string(self):
        tier = get_tier("business")
        assert tier.name is TierName.BUSINESS

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError):
            get_tier("unknown")


# ---------------------------------------------------------------------------
# is_within_run_limit
# ---------------------------------------------------------------------------


class TestRunLimits:
    def test_zero_runs_always_within_limit(self):
        for tier in TierName:
            assert is_within_run_limit(tier, 0)

    def test_at_limit_is_not_within(self):
        limit = TIERS[TierName.STARTER].limits.runs_per_month
        assert not is_within_run_limit(TierName.STARTER, limit)

    def test_below_limit_is_within(self):
        limit = TIERS[TierName.STARTER].limits.runs_per_month
        assert is_within_run_limit(TierName.STARTER, limit - 1)

    def test_above_limit_is_not_within(self):
        limit = TIERS[TierName.STARTER].limits.runs_per_month
        assert not is_within_run_limit(TierName.STARTER, limit + 1)


# ---------------------------------------------------------------------------
# build_checkout_session_params
# ---------------------------------------------------------------------------


class TestBuildCheckoutSessionParams:
    def test_raises_when_price_id_not_configured(self):
        """Raises RuntimeError when the env-var for the Price ID is not set."""
        env_var = TIERS[TierName.STARTER].stripe_price_id_env_var
        original = os.environ.pop(env_var, None)
        try:
            with pytest.raises(RuntimeError, match="not configured"):
                build_checkout_session_params(
                    TierName.STARTER,
                    "user@example.com",
                    "https://example.com/success",
                    "https://example.com/cancel",
                )
        finally:
            if original is not None:
                os.environ[env_var] = original

    def test_returns_correct_params_when_configured(self, monkeypatch):
        env_var = TIERS[TierName.PRO].stripe_price_id_env_var
        monkeypatch.setenv(env_var, "price_test_pro_123")
        params = build_checkout_session_params(
            TierName.PRO,
            "user@example.com",
            "https://example.com/success",
            "https://example.com/cancel",
        )
        assert params["mode"] == "subscription"
        assert params["customer_email"] == "user@example.com"
        assert params["line_items"][0]["price"] == "price_test_pro_123"
        assert params["metadata"]["tier"] == "pro"


# ---------------------------------------------------------------------------
# resolve_tier_from_webhook
# ---------------------------------------------------------------------------


class TestResolveWebhookTier:
    def _make_event(self, event_type: str, tier: str | None) -> dict:
        metadata = {"tier": tier} if tier else {}
        return {
            "type": event_type,
            "data": {"object": {"metadata": metadata, "customer_email": "x@y.com"}},
        }

    def test_checkout_completed_returns_tier(self):
        event = self._make_event("checkout.session.completed", "enterprise")
        assert resolve_tier_from_webhook(event) is TierName.ENTERPRISE

    def test_wrong_event_type_returns_none(self):
        event = self._make_event("customer.subscription.deleted", "pro")
        assert resolve_tier_from_webhook(event) is None

    def test_unknown_tier_returns_none(self):
        event = self._make_event("checkout.session.completed", "unknown_tier")
        assert resolve_tier_from_webhook(event) is None

    def test_missing_tier_metadata_returns_none(self):
        event = self._make_event("checkout.session.completed", None)
        assert resolve_tier_from_webhook(event) is None

    def test_all_valid_tiers_resolved(self):
        for tier in TierName:
            event = self._make_event("checkout.session.completed", tier.value)
            assert resolve_tier_from_webhook(event) is tier


# ---------------------------------------------------------------------------
# stripe_price_id property
# ---------------------------------------------------------------------------


class TestStripePriceIdProperty:
    def test_returns_none_when_env_var_unset(self):
        tier = TIERS[TierName.STARTER]
        env_var = tier.stripe_price_id_env_var
        original = os.environ.pop(env_var, None)
        try:
            assert tier.stripe_price_id is None
        finally:
            if original is not None:
                os.environ[env_var] = original

    def test_returns_value_when_env_var_set(self, monkeypatch):
        tier = TIERS[TierName.ENTERPRISE]
        monkeypatch.setenv(tier.stripe_price_id_env_var, "price_ent_999")
        assert tier.stripe_price_id == "price_ent_999"
