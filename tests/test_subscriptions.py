"""Unit tests for subscriptions.py — SaaS tier definitions and entitlement gating."""

import os

import pytest # type: ignore

from council.models.subscriptions import (
    TierName,
    TIERS,
    TIER_ORDER,
    UsageLimits,
    SubscriptionTier,
    DEFAULT_TRIAL_DAYS,
    get_tier,
    tier_allows_feature,
    is_within_run_limit,
    get_trial_days,
    build_payment_link_params,
    resolve_tier_from_webhook,
)


class TestTierCatalog:
    def test_all_five_tiers_defined(self):
        assert set(TIERS.keys()) == {
            TierName.TRIAL,
            TierName.BASIC,
            TierName.PRO,
            TierName.ULTRA,
            TierName.ENTERPRISE,
        }

    def test_tier_order_is_ascending(self):
        assert TIER_ORDER == [
            TierName.TRIAL,
            TierName.BASIC,
            TierName.PRO,
            TierName.ULTRA,
            TierName.ENTERPRISE,
        ]

    def test_paid_tier_prices_follow_basic_pro_ultra_shape(self):
        assert TIERS[TierName.BASIC].price_usd_monthly < TIERS[TierName.PRO].price_usd_monthly
        assert TIERS[TierName.PRO].price_usd_monthly < TIERS[TierName.ULTRA].price_usd_monthly
        # Enterprise is contract-priced (range in sales flow), so catalog stores a floor value.
        assert TIERS[TierName.ENTERPRISE].price_usd_monthly >= 25

    def test_each_tier_has_required_fields(self):
        for tier in TIERS.values():
            assert isinstance(tier, SubscriptionTier)
            assert tier.display_name
            assert tier.stripe_price_id_env_var is None or tier.stripe_price_id_env_var
            assert tier.description
            assert isinstance(tier.limits, UsageLimits)
            assert len(tier.features) >= 1

    def test_prices_match_spec(self):
        assert TIERS[TierName.TRIAL].price_usd_monthly == 0
        assert TIERS[TierName.BASIC].price_usd_monthly == 10
        assert TIERS[TierName.PRO].price_usd_monthly == 20
        assert TIERS[TierName.ULTRA].price_usd_monthly == 200
        assert TIERS[TierName.ENTERPRISE].price_usd_monthly == 25


class TestUsageLimitsOrdering:
    def test_runs_non_decreasing_for_paid_tiers(self):
        paid = [TierName.BASIC, TierName.PRO, TierName.ULTRA, TierName.ENTERPRISE]
        runs = [TIERS[t].limits.runs_per_month for t in paid]
        assert runs == sorted(runs)

    def test_max_agents_non_decreasing_for_paid_tiers(self):
        paid = [TierName.BASIC, TierName.PRO, TierName.ULTRA, TierName.ENTERPRISE]
        agents = [TIERS[t].limits.max_agents for t in paid]
        assert agents == sorted(agents)

    def test_input_tokens_non_decreasing_for_paid_tiers(self):
        paid = [TierName.BASIC, TierName.PRO, TierName.ULTRA, TierName.ENTERPRISE]
        tokens = [TIERS[t].limits.max_input_tokens for t in paid]
        assert tokens == sorted(tokens)


class TestFeatureGating:
    def test_basic_no_ide_plugins(self):
        assert not tier_allows_feature(TierName.BASIC, "ide_plugins")

    def test_pro_has_mcp_and_custom_mcp(self):
        assert tier_allows_feature(TierName.PRO, "mcp")
        assert tier_allows_feature(TierName.PRO, "custom_mcp")

    def test_ultra_has_computer_use_and_cua(self):
        assert tier_allows_feature(TierName.ULTRA, "computer_use")
        assert tier_allows_feature(TierName.ULTRA, "cua")

    def test_enterprise_has_sso_and_billing(self):
        assert tier_allows_feature(TierName.ENTERPRISE, "sso")
        assert tier_allows_feature(TierName.ENTERPRISE, "centralized_billing")

    def test_enterprise_has_unlimited_personas(self):
        assert tier_allows_feature(TierName.ENTERPRISE, "personas_unlimited")

    def test_string_tier_name_accepted(self):
        assert not tier_allows_feature("basic", "computer_use")
        assert tier_allows_feature("ultra", "computer_use")

    def test_unknown_feature_raises(self):
        with pytest.raises(ValueError, match="Unknown feature key"):
            tier_allows_feature(TierName.PRO, "not_real")

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError):
            tier_allows_feature("diamond", "mcp")


class TestGetTier:
    def test_returns_correct_tier_by_enum(self):
        tier = get_tier(TierName.PRO)
        assert tier.name is TierName.PRO

    def test_returns_correct_tier_by_string(self):
        tier = get_tier("ultra")
        assert tier.name is TierName.ULTRA

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError):
            get_tier("unknown")


class TestRunLimits:
    def test_zero_runs_always_within_limit(self):
        for tier in TierName:
            assert is_within_run_limit(tier, 0)

    def test_at_limit_is_not_within(self):
        limit = TIERS[TierName.BASIC].limits.runs_per_month
        assert not is_within_run_limit(TierName.BASIC, limit)

    def test_below_limit_is_within(self):
        limit = TIERS[TierName.BASIC].limits.runs_per_month
        assert is_within_run_limit(TierName.BASIC, limit - 1)


class TestTrialPeriod:
    def test_default_trial_days(self, monkeypatch):
        monkeypatch.delenv("TRIAL_PERIOD_DAYS", raising=False)
        assert get_trial_days() == DEFAULT_TRIAL_DAYS

    def test_env_trial_days(self, monkeypatch):
        monkeypatch.setenv("TRIAL_PERIOD_DAYS", "21")
        assert get_trial_days() == 21

    def test_invalid_env_trial_days_falls_back(self, monkeypatch):
        monkeypatch.setenv("TRIAL_PERIOD_DAYS", "not-a-number")
        assert get_trial_days() == DEFAULT_TRIAL_DAYS


class TestBuildPaymentLinkParams:
    def test_trial_tier_is_not_billable(self):
        with pytest.raises(RuntimeError, match="non-billable"):
            build_payment_link_params(TierName.TRIAL, "https://example.com/success")

    def test_raises_when_price_id_not_configured(self):
        env_var = TIERS[TierName.BASIC].stripe_price_id_env_var
        assert env_var is not None
        original = os.environ.pop(env_var, None)
        try:
            with pytest.raises(RuntimeError, match="not configured"):
                build_payment_link_params(TierName.BASIC, "https://example.com/success")
        finally:
            if original is not None:
                os.environ[env_var] = original

    def test_returns_correct_params_when_configured(self, monkeypatch):
        env_var = TIERS[TierName.PRO].stripe_price_id_env_var
        assert env_var is not None
        monkeypatch.setenv(env_var, "price_test_pro_123")
        monkeypatch.setenv("TRIAL_PERIOD_DAYS", "14")
        params = build_payment_link_params(
            TierName.PRO,
            "https://example.com/success",
            customer_email="user@example.com",
        )
        assert params["line_items"][0]["price"] == "price_test_pro_123"
        assert params["metadata"]["tier"] == "pro"
        assert params["metadata"]["customer_email_hint"] == "user@example.com"
        assert params["subscription_data"]["metadata"]["tier"] == "pro"
        assert params["subscription_data"]["trial_period_days"] == 14


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

    def test_subscription_updated_returns_tier(self):
        event = self._make_event("customer.subscription.updated", "ultra")
        assert resolve_tier_from_webhook(event) is TierName.ULTRA

    def test_wrong_event_type_returns_none(self):
        event = self._make_event("invoice.paid", "pro")
        assert resolve_tier_from_webhook(event) is None

    def test_unknown_tier_returns_none(self):
        event = self._make_event("checkout.session.completed", "unknown_tier")
        assert resolve_tier_from_webhook(event) is None

    def test_all_valid_tiers_resolved(self):
        for tier in TierName:
            if tier is TierName.TRIAL:
                continue
            event = self._make_event("checkout.session.completed", tier.value)
            assert resolve_tier_from_webhook(event) is tier


class TestStripePriceIdProperty:
    def test_trial_has_no_price_id(self):
        assert TIERS[TierName.TRIAL].stripe_price_id is None

    def test_returns_value_when_env_var_set(self, monkeypatch):
        tier = TIERS[TierName.ENTERPRISE]
        env_var = tier.stripe_price_id_env_var
        assert env_var is not None
        monkeypatch.setenv(env_var, "price_ent_999")
        assert tier.stripe_price_id == "price_ent_999"
