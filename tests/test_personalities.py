"""
Unit tests for personality mode switching, MBTI profile generation, and canned personalities.
"""

import pytest

from personalities import (
    PersonalityMode,
    JobRole,
    JOB_ROLE_INSTRUCTIONS,
    MBTI_TRAITS,
    generate_mbti_personality,
    get_canned_personalities,
    build_agent_panel,
    parse_dynamic_agents,
    _build_generated_system_prompt,
)
from council import Agent, _resolve_default_agents


# ---------------------------------------------------------------------------
# PersonalityMode tests
# ---------------------------------------------------------------------------


class TestPersonalityMode:
    def test_all_modes_exist(self):
        """All four personality modes are defined."""
        modes = {m.value for m in PersonalityMode}
        assert modes == {"canned", "dynamic", "hybrid", "generated"}

    def test_mode_from_string(self):
        """PersonalityMode can be constructed from its value string."""
        assert PersonalityMode("canned") == PersonalityMode.CANNED
        assert PersonalityMode("dynamic") == PersonalityMode.DYNAMIC
        assert PersonalityMode("hybrid") == PersonalityMode.HYBRID
        assert PersonalityMode("generated") == PersonalityMode.GENERATED

    def test_invalid_mode_raises(self):
        """Invalid mode strings raise ValueError."""
        with pytest.raises(ValueError):
            PersonalityMode("unknown_mode")

    def test_mode_is_enum(self):
        """PersonalityMode members are Enum instances."""
        for mode in PersonalityMode:
            assert isinstance(mode, PersonalityMode)


# ---------------------------------------------------------------------------
# JobRole tests
# ---------------------------------------------------------------------------


class TestJobRole:
    def test_all_roles_exist(self):
        """All five job roles are defined."""
        expected = {
            "Devil's Advocate",
            "Moderator",
            "Domain Expert",
            "Contrarian",
            "Synthesizer",
        }
        actual = {jr.value for jr in JobRole}
        assert actual == expected

    def test_each_role_has_instruction(self):
        """Every JobRole has a non-empty instruction string."""
        for role in JobRole:
            assert role in JOB_ROLE_INSTRUCTIONS
            assert len(JOB_ROLE_INSTRUCTIONS[role]) > 20


# ---------------------------------------------------------------------------
# MBTI profile generation tests (Feature 3)
# ---------------------------------------------------------------------------


class TestMBTIGeneration:
    def test_all_16_types_defined(self):
        """All 16 MBTI types are present in MBTI_TRAITS."""
        expected = {
            "INTJ", "INTP", "ENTJ", "ENTP",
            "INFJ", "INFP", "ENFJ", "ENFP",
            "ISTJ", "ISFJ", "ESTJ", "ESFJ",
            "ISTP", "ISFP", "ESTP", "ESFP",
        }
        assert set(MBTI_TRAITS.keys()) == expected

    def test_each_type_has_required_fields(self):
        """Each MBTI type has traits, reasoning_style, communication_tone, and debate_behavior."""
        for mbti_type, data in MBTI_TRAITS.items():
            assert "traits" in data, f"{mbti_type} missing 'traits'"
            assert "reasoning_style" in data, f"{mbti_type} missing 'reasoning_style'"
            assert "communication_tone" in data, f"{mbti_type} missing 'communication_tone'"
            assert "debate_behavior" in data, f"{mbti_type} missing 'debate_behavior'"
            assert len(data["traits"]) >= 3, f"{mbti_type} has fewer than 3 traits"

    def test_generate_mbti_returns_dict(self):
        """generate_mbti_personality returns a dict with required keys."""
        result = generate_mbti_personality("INTJ")
        assert isinstance(result, dict)
        for key in ("name", "role", "system_prompt", "color"):
            assert key in result, f"Missing key: {key}"

    def test_generate_mbti_default_name(self):
        """Default name is 'The <TYPE>'."""
        result = generate_mbti_personality("ENFP")
        assert result["name"] == "The ENFP"

    def test_generate_mbti_custom_name(self):
        """Custom name overrides the default."""
        result = generate_mbti_personality("INTJ", name="Alice")
        assert result["name"] == "Alice"

    def test_generate_mbti_case_insensitive(self):
        """generate_mbti_personality accepts lowercase type strings."""
        result = generate_mbti_personality("intj")
        assert result["mbti_type"] == "INTJ"

    def test_generate_mbti_invalid_type_raises(self):
        """Unknown MBTI type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown MBTI type"):
            generate_mbti_personality("XXXX")

    def test_generate_mbti_system_prompt_contains_type(self):
        """Generated system prompt mentions the MBTI type."""
        result = generate_mbti_personality("ESTP")
        assert "ESTP" in result["system_prompt"]

    def test_generate_mbti_with_job_role(self):
        """Job role instructions are injected into the system prompt."""
        result = generate_mbti_personality("INTP", job_role=JobRole.CONTRARIAN)
        assert "CONTRARIAN" in result["system_prompt"].upper()
        assert result["job_role"] == JobRole.CONTRARIAN

    def test_generate_mbti_without_job_role(self):
        """No job role means job_role key is None."""
        result = generate_mbti_personality("ISFJ")
        assert result["job_role"] is None

    @pytest.mark.parametrize("mbti_type", list(MBTI_TRAITS.keys()))
    def test_generate_all_types_no_error(self, mbti_type):
        """generate_mbti_personality succeeds for every valid MBTI type."""
        result = generate_mbti_personality(mbti_type)
        assert result["name"] == f"The {mbti_type}"
        assert len(result["system_prompt"]) > 50


# ---------------------------------------------------------------------------
# Canned personalities tests (Feature 1)
# ---------------------------------------------------------------------------


class TestCannedPersonalities:
    def test_five_canned_personalities(self):
        """Exactly 5 canned personalities are defined."""
        canned = get_canned_personalities()
        assert len(canned) == 5

    def test_canned_names(self):
        """Canned personalities have the expected names."""
        canned = get_canned_personalities()
        names = {p["name"] for p in canned}
        assert "The Skeptic" in names
        assert "The Optimist" in names
        assert "The Realist" in names
        assert "The Visionary" in names
        assert "The Analyst" in names

    def test_canned_have_required_fields(self):
        """Each canned personality has name, role, system_prompt, color."""
        for p in get_canned_personalities():
            for key in ("name", "role", "system_prompt", "color"):
                assert key in p, f"Canned personality '{p.get('name')}' missing '{key}'"

    def test_canned_returns_copy(self):
        """get_canned_personalities returns a fresh copy each call."""
        a = get_canned_personalities()
        b = get_canned_personalities()
        assert a is not b
        a[0]["name"] = "Modified"
        assert b[0]["name"] != "Modified"

    def test_canned_system_prompts_non_empty(self):
        """All canned system prompts are non-trivially long."""
        for p in get_canned_personalities():
            assert len(p["system_prompt"]) > 100, (
                f"System prompt for '{p['name']}' is too short"
            )


# ---------------------------------------------------------------------------
# build_agent_panel mode switching tests (Feature 1)
# ---------------------------------------------------------------------------


class TestBuildAgentPanel:
    def _base_agents(self):
        return get_canned_personalities()

    def test_canned_mode_returns_five(self):
        """CANNED mode always returns 5 agents."""
        panel = build_agent_panel(PersonalityMode.CANNED, self._base_agents())
        assert len(panel) == 5

    def test_canned_mode_has_expected_names(self):
        """CANNED mode returns the 5 predefined personas."""
        panel = build_agent_panel(PersonalityMode.CANNED, self._base_agents())
        names = {p["name"] for p in panel}
        assert "The Skeptic" in names
        assert "The Optimist" in names

    def test_dynamic_mode_returns_five(self):
        """DYNAMIC mode (sync stub) returns 5 MBTI-based agents."""
        panel = build_agent_panel(PersonalityMode.DYNAMIC, self._base_agents(), topic="AI safety")
        assert len(panel) == 5

    def test_dynamic_mode_topic_in_role(self):
        """DYNAMIC mode annotates the role with the topic."""
        panel = build_agent_panel(PersonalityMode.DYNAMIC, self._base_agents(), topic="climate")
        for p in panel:
            assert "climate" in p["role"]

    def test_hybrid_mode_returns_five(self):
        """HYBRID mode returns 5 agents (3 canned + 2 dynamic)."""
        panel = build_agent_panel(PersonalityMode.HYBRID, self._base_agents())
        assert len(panel) == 5

    def test_hybrid_mode_contains_canned(self):
        """HYBRID mode includes at least the first canned persona."""
        panel = build_agent_panel(PersonalityMode.HYBRID, self._base_agents())
        names = [p["name"] for p in panel]
        assert "The Skeptic" in names

    def test_generated_mode_no_data_falls_back_to_canned(self):
        """GENERATED mode with no data falls back to 5 canned personas."""
        panel = build_agent_panel(PersonalityMode.GENERATED, [], generated_data=None)
        assert len(panel) == 5

    def test_generated_mode_with_data(self):
        """GENERATED mode with person data creates agents from that data."""
        data = [
            {
                "name": "Zara Helios",
                "data": "Fictional entrepreneur obsessed with starships, orbital habitats, and open debate.",
                "color": "blue",
            },
            {
                "name": "Magnus Evergreen",
                "data": "Fictional long-term investor known for patient strategies and quirky parables.",
                "color": "green",
            },
        ]
        panel = build_agent_panel(PersonalityMode.GENERATED, [], generated_data=data)
        assert len(panel) == 2
        names = [p["name"] for p in panel]
        assert "Zara Helios" in names
        assert "Magnus Evergreen" in names

    def test_generated_mode_skips_inactive_personas(self):
        """GENERATED mode excludes personas where active is false."""
        data = [
            {
                "name": "Active Persona",
                "data": "Active profile data.",
                "active": True,
            },
            {
                "name": "Inactive Persona",
                "data": "Inactive profile data.",
                "active": False,
            },
        ]
        panel = build_agent_panel(PersonalityMode.GENERATED, [], generated_data=data)
        names = [p["name"] for p in panel]
        assert names == ["Active Persona"]

    def test_generated_mode_defaults_active_true(self):
        """Missing active field defaults to included/active persona."""
        data = [{"name": "Default Active", "data": "Profile data."}]
        panel = build_agent_panel(PersonalityMode.GENERATED, [], generated_data=data)
        assert len(panel) == 1
        assert panel[0]["active"] is True

    def test_generated_mode_system_prompt_contains_name(self):
        """GENERATED personas have their name in their system prompt."""
        data = [
            {
                "name": "Lyra Quill",
                "data": "Fictional pioneer of mechanical computation and analytical engines.",
                "color": "cyan",
            }
        ]
        panel = build_agent_panel(PersonalityMode.GENERATED, [], generated_data=data)
        assert "Lyra Quill" in panel[0]["system_prompt"]

    def test_default_mode_appends_active_generated_personas(self):
        """Default council should include base agents followed by active generated personas."""
        base_agents = [
            Agent(name="Base One", role="Base", system_prompt="A", color="blue"),
            Agent(name="Base Two", role="Base", system_prompt="B", color="green"),
        ]
        generated_data = [
            {"name": "Generated One", "data": "Profile A", "active": True},
            {"name": "Generated Two", "data": "Profile B", "active": True},
        ]

        merged = _resolve_default_agents(base_agents, generated_data)
        assert [a.name for a in merged] == [
            "Base One",
            "Base Two",
            "Generated One",
            "Generated Two",
        ]

    def test_default_mode_excludes_inactive_generated_personas(self):
        """Inactive generated personas should not be appended in default mode."""
        base_agents = [
            Agent(name="Base", role="Base", system_prompt="A", color="blue"),
        ]
        generated_data = [
            {"name": "Generated Active", "data": "Profile A", "active": True},
            {"name": "Generated Inactive", "data": "Profile B", "active": False},
        ]

        merged = _resolve_default_agents(base_agents, generated_data)
        assert [a.name for a in merged] == ["Base", "Generated Active"]

    def test_default_mode_name_collision_prefers_base_agent(self):
        """When names collide, default merge keeps the base/YAML agent and skips generated duplicate."""
        base_agents = [
            Agent(name="Kavin Shah", role="Base", system_prompt="A", color="blue"),
        ]
        generated_data = [
            {"name": "kavin shah", "data": "Generated profile", "active": True},
            {"name": "Another Persona", "data": "Generated profile", "active": True},
        ]

        merged = _resolve_default_agents(base_agents, generated_data)
        assert [a.name for a in merged] == ["Kavin Shah", "Another Persona"]

    def test_mode_isolation(self):
        """Different modes return distinct agent sets."""
        canned = build_agent_panel(PersonalityMode.CANNED, self._base_agents())
        hybrid = build_agent_panel(PersonalityMode.HYBRID, self._base_agents())
        # They share some names (canned carries over) but are different objects
        canned_names = {p["name"] for p in canned}
        hybrid_names = {p["name"] for p in hybrid}
        # Hybrid has ENTJ and INFP which are not in canned
        assert hybrid_names - canned_names  # some names unique to hybrid


# ---------------------------------------------------------------------------
# Dynamic agent parser tests
# ---------------------------------------------------------------------------


class TestParseDynamicAgents:
    def _make_raw(self, name, role, color, system_prompt):
        return (
            f"===AGENT===\n"
            f"NAME: {name}\n"
            f"ROLE: {role}\n"
            f"COLOR: {color}\n"
            f"SYSTEM_PROMPT:\n{system_prompt}\n"
            f"===END===\n"
        )

    def test_parse_single_agent(self):
        """Parses a well-formed single agent block."""
        raw = self._make_raw("The Regulator", "Policy Expert", "blue", "You are The Regulator.")
        agents = parse_dynamic_agents(raw)
        assert len(agents) == 1
        assert agents[0]["name"] == "The Regulator"
        assert agents[0]["role"] == "Policy Expert"
        assert agents[0]["color"] == "blue"

    def test_parse_multiple_agents(self):
        """Parses multiple consecutive agent blocks."""
        raw = (
            self._make_raw("Agent A", "Role A", "red", "Prompt A.")
            + self._make_raw("Agent B", "Role B", "green", "Prompt B.")
        )
        agents = parse_dynamic_agents(raw)
        assert len(agents) == 2
        assert agents[0]["name"] == "Agent A"
        assert agents[1]["name"] == "Agent B"

    def test_parse_empty_string(self):
        """Empty input returns empty list."""
        assert parse_dynamic_agents("") == []

    def test_parse_missing_end_marker(self):
        """Blocks without ===END=== are skipped."""
        raw = "===AGENT===\nNAME: Broken\nROLE: Missing End\n"
        assert parse_dynamic_agents(raw) == []

    def test_parse_system_prompt_content(self):
        """System prompt content is correctly captured."""
        raw = self._make_raw(
            "The Analyst",
            "Data Expert",
            "cyan",
            "You are The Analyst.\nFocus on data.",
        )
        agents = parse_dynamic_agents(raw)
        assert "You are The Analyst." in agents[0]["system_prompt"]

    def test_default_color_when_missing(self):
        """Missing COLOR defaults to 'cyan'."""
        raw = "===AGENT===\nNAME: Nameless\nROLE: Roleless\nSYSTEM_PROMPT:\nSome prompt.\n===END==="
        agents = parse_dynamic_agents(raw)
        assert len(agents) == 1
        assert agents[0]["color"] == "cyan"


# ---------------------------------------------------------------------------
# Generated system prompt helper
# ---------------------------------------------------------------------------


class TestBuildGeneratedSystemPrompt:
    def test_prompt_contains_name(self):
        prompt = _build_generated_system_prompt("Marie Curie", "Discovered radium.")
        assert "Marie Curie" in prompt

    def test_prompt_contains_data_excerpt(self):
        prompt = _build_generated_system_prompt("Einstein", "Developed relativity.")
        assert "Developed relativity." in prompt

    def test_prompt_handles_empty_data(self):
        prompt = _build_generated_system_prompt("Unknown", "")
        assert "Unknown" in prompt
        assert "(no data provided)" in prompt

    def test_prompt_truncates_long_data(self):
        long_data = "x" * 5000
        prompt = _build_generated_system_prompt("Test", long_data)
        # System prompt should not include all 5000 chars
        assert len(prompt) < 5000
