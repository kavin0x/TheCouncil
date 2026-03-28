"""
Unit tests for the refactored resolution pipeline:
  - _get_top3_resolutions  — top-3 extraction with vote-based ranking
  - _parse_moderator_json  — structured pros/cons JSON parsing
  - ResolutionAnalysis / ModeratorReport dataclasses
"""

from council.core.council import (
    Agent,
    DebateSession,
    ModeratorReport,
    ResolutionAnalysis,
    _get_top3_resolutions,
    _parse_moderator_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(name: str, role: str = "Analyst") -> Agent:
    return Agent(name=name, role=role, system_prompt="You are a test agent.")


def _make_session(
    resolutions: dict[str, str],
    vote_rounds: list[dict[str, str]] | None = None,
) -> DebateSession:
    agents = [_make_agent(name) for name in resolutions]
    session = DebateSession(question="Test question?", agents=agents)
    session.resolutions = resolutions
    if vote_rounds is not None:
        session.vote_rounds = vote_rounds
    return session


# ---------------------------------------------------------------------------
# _get_top3_resolutions
# ---------------------------------------------------------------------------


class TestGetTop3Resolutions:
    def test_clear_winner_first(self):
        """Agent with most votes appears at rank 1."""
        resolutions = {"Alice": "R-Alice", "Bob": "R-Bob", "Carol": "R-Carol"}
        votes = {"v1": "Bob", "v2": "Bob", "v3": "Alice"}
        session = _make_session(resolutions, vote_rounds=[votes])
        top3 = _get_top3_resolutions(session)
        assert top3[0][0] == "Bob"
        assert top3[0][2] == 2

    def test_returns_at_most_three(self):
        """Never returns more than 3 entries."""
        resolutions = {f"Agent{i}": f"R{i}" for i in range(6)}
        votes = {f"v{i}": f"Agent{i % 6}" for i in range(6)}
        session = _make_session(resolutions, vote_rounds=[votes])
        top3 = _get_top3_resolutions(session)
        assert len(top3) <= 3

    def test_fewer_than_three_agents(self):
        """Works correctly when fewer than 3 resolutions exist."""
        resolutions = {"Alpha": "R-Alpha", "Beta": "R-Beta"}
        votes = {"v1": "Alpha", "v2": "Beta"}
        session = _make_session(resolutions, vote_rounds=[votes])
        top3 = _get_top3_resolutions(session)
        assert len(top3) == 2

    def test_no_votes_returns_insertion_order(self):
        """With no vote rounds, returns resolutions in insertion order."""
        resolutions = {"A": "RA", "B": "RB", "C": "RC"}
        session = _make_session(resolutions, vote_rounds=[])
        top3 = _get_top3_resolutions(session)
        names = [entry[0] for entry in top3]
        assert names == ["A", "B", "C"]

    def test_tie_broken_by_insertion_order(self):
        """Tied vote counts are broken by insertion order (earlier = higher rank)."""
        resolutions = {"First": "RF", "Second": "RS", "Third": "RT"}
        votes = {"v1": "First", "v2": "Second", "v3": "Third"}  # all tied at 1
        session = _make_session(resolutions, vote_rounds=[votes])
        top3 = _get_top3_resolutions(session)
        assert top3[0][0] == "First"
        assert top3[1][0] == "Second"
        assert top3[2][0] == "Third"

    def test_uses_first_vote_round_for_ranking(self):
        """Ranking uses the first vote round, not later tiebreaker rounds."""
        resolutions = {"X": "RX", "Y": "RY", "Z": "RZ"}
        round1 = {"v1": "X", "v2": "X", "v3": "Y"}  # X clearly ahead
        round2 = {"v1": "Y", "v2": "Y", "v3": "Y"}  # Y wins tiebreaker
        session = _make_session(resolutions, vote_rounds=[round1, round2])
        top3 = _get_top3_resolutions(session)
        # Must use round1 for ranking → X first
        assert top3[0][0] == "X"

    def test_resolution_text_preserved(self):
        """Resolution text is preserved verbatim in the tuple."""
        resolutions = {"Aria": "The council must act now.", "Bex": "Wait and see."}
        votes = {"v1": "Aria", "v2": "Aria"}
        session = _make_session(resolutions, vote_rounds=[votes])
        top3 = _get_top3_resolutions(session)
        assert top3[0][1] == "The council must act now."

    def test_zero_vote_agents_included_if_in_top3(self):
        """Agents with zero votes can still appear in top-3 if < 3 agents have votes."""
        resolutions = {"Voted": "R1", "Unvoted": "R2"}
        votes = {"v1": "Voted"}
        session = _make_session(resolutions, vote_rounds=[votes])
        top3 = _get_top3_resolutions(session)
        names = [t[0] for t in top3]
        assert "Voted" in names
        assert "Unvoted" in names


# ---------------------------------------------------------------------------
# _parse_moderator_json
# ---------------------------------------------------------------------------


class TestParseModeratorJson:
    def _top3(self):
        return [
            ("Alice", "Alice resolution text.", 3),
            ("Bob", "Bob resolution text.", 2),
            ("Carol", "Carol resolution text.", 1),
        ]

    def _agents(self):
        return [
            _make_agent("Alice", "Strategist"),
            _make_agent("Bob", "Engineer"),
            _make_agent("Carol", "Designer"),
        ]

    def test_valid_json_parses_correctly(self):
        """Valid JSON with all fields is parsed into a correct ModeratorReport."""
        raw = """{
  "analyses": [
    {"rank": 1, "summary": "Go now.", "pros": ["Fast", "Bold"], "cons": ["Risky"]},
    {"rank": 2, "summary": "Wait.", "pros": ["Safe"], "cons": ["Slow", "Missed opp"]},
    {"rank": 3, "summary": "Hybrid.", "pros": ["Balanced"], "cons": ["Complex"]}
  ]
}"""
        report = _parse_moderator_json(raw, self._top3(), self._agents())
        assert isinstance(report, ModeratorReport)
        assert len(report.analyses) == 3
        assert report.analyses[0].rank == 1
        assert report.analyses[0].summary == "Go now."
        assert report.analyses[0].pros == ["Fast", "Bold"]
        assert report.analyses[0].cons == ["Risky"]

    def test_agent_name_and_role_injected(self):
        """Agent name and role from top3 list are injected into each analysis."""
        raw = """{
  "analyses": [
    {"rank": 1, "summary": "S1", "pros": ["P1"], "cons": ["C1"]},
    {"rank": 2, "summary": "S2", "pros": ["P2"], "cons": ["C2"]},
    {"rank": 3, "summary": "S3", "pros": ["P3"], "cons": ["C3"]}
  ]
}"""
        report = _parse_moderator_json(raw, self._top3(), self._agents())
        assert report.analyses[0].agent_name == "Alice"
        assert report.analyses[0].agent_role == "Strategist"
        assert report.analyses[1].agent_name == "Bob"
        assert report.analyses[2].agent_name == "Carol"

    def test_resolution_text_preserved(self):
        """Resolution text from top3 appears in the analysis."""
        raw = """{
  "analyses": [
    {"rank": 1, "summary": "S", "pros": ["P"], "cons": ["C"]},
    {"rank": 2, "summary": "S", "pros": ["P"], "cons": ["C"]},
    {"rank": 3, "summary": "S", "pros": ["P"], "cons": ["C"]}
  ]
}"""
        report = _parse_moderator_json(raw, self._top3(), self._agents())
        assert report.analyses[0].resolution == "Alice resolution text."

    def test_invalid_json_returns_fallback(self):
        """Invalid JSON produces fallback entries without crashing."""
        raw = "not valid json at all %%"
        report = _parse_moderator_json(raw, self._top3(), self._agents())
        assert isinstance(report, ModeratorReport)
        assert len(report.analyses) == 3
        for a in report.analyses:
            assert a.summary == "(summary unavailable)"

    def test_empty_string_returns_fallback(self):
        """Empty response produces fallback entries."""
        report = _parse_moderator_json("", self._top3(), self._agents())
        assert len(report.analyses) == 3

    def test_markdown_fenced_json_stripped(self):
        """JSON wrapped in ```json fences is still parsed correctly."""
        raw = """```json
{
  "analyses": [
    {"rank": 1, "summary": "Go.", "pros": ["A"], "cons": ["B"]},
    {"rank": 2, "summary": "Wait.", "pros": ["C"], "cons": ["D"]},
    {"rank": 3, "summary": "Try.", "pros": ["E"], "cons": ["F"]}
  ]
}
```"""
        report = _parse_moderator_json(raw, self._top3(), self._agents())
        assert report.analyses[0].summary == "Go."

    def test_partial_analyses_padded_with_fallback(self):
        """If the model returns fewer analyses than top3 entries, remainder are fallbacks."""
        raw = """{
  "analyses": [
    {"rank": 1, "summary": "Only one.", "pros": ["A"], "cons": ["B"]}
  ]
}"""
        report = _parse_moderator_json(raw, self._top3(), self._agents())
        assert len(report.analyses) == 3
        assert report.analyses[1].summary == "(summary unavailable)"
        assert report.analyses[2].summary == "(summary unavailable)"

    def test_two_entry_top3(self):
        """Works correctly when fewer than 3 resolutions exist."""
        top3 = [("Alice", "R-A", 2), ("Bob", "R-B", 1)]
        agents = [_make_agent("Alice", "Lead"), _make_agent("Bob", "Dev")]
        raw = """{
  "analyses": [
    {"rank": 1, "summary": "Alice wins.", "pros": ["Strong"], "cons": ["Cost"]},
    {"rank": 2, "summary": "Bob tries.", "pros": ["Cheap"], "cons": ["Slow"]}
  ]
}"""
        report = _parse_moderator_json(raw, top3, agents)
        assert len(report.analyses) == 2


# ---------------------------------------------------------------------------
# ResolutionAnalysis dataclass
# ---------------------------------------------------------------------------


class TestResolutionAnalysis:
    def test_dataclass_fields(self):
        """ResolutionAnalysis holds all expected fields."""
        ra = ResolutionAnalysis(
            rank=1,
            agent_name="Ada",
            agent_role="Engineer",
            resolution="We should act.",
            summary="Act decisively.",
            pros=["Fast", "Bold"],
            cons=["Risky"],
        )
        assert ra.rank == 1
        assert ra.agent_name == "Ada"
        assert ra.agent_role == "Engineer"
        assert ra.resolution == "We should act."
        assert ra.summary == "Act decisively."
        assert ra.pros == ["Fast", "Bold"]
        assert ra.cons == ["Risky"]


# ---------------------------------------------------------------------------
# ModeratorReport dataclass
# ---------------------------------------------------------------------------


class TestModeratorReport:
    def test_empty_report(self):
        """ModeratorReport can be constructed with an empty analyses list."""
        report = ModeratorReport(analyses=[])
        assert report.analyses == []

    def test_report_with_analyses(self):
        """ModeratorReport holds multiple ResolutionAnalysis entries."""
        a1 = ResolutionAnalysis(1, "A", "r", "res", "sum", ["p"], ["c"])
        a2 = ResolutionAnalysis(2, "B", "r", "res", "sum", ["p"], ["c"])
        report = ModeratorReport(analyses=[a1, a2])
        assert len(report.analyses) == 2
        assert report.analyses[0].rank == 1
