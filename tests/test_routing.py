"""Test cases for confidence-based routing.

Thresholds are read from config/routing.yaml (currently 60/40) — never
hardcoded. LLM-tier tests use mocked providers (no API keys, no env vars).
"""
import sys
sys.path.insert(0, '.')
from backend.routing import compute_overall_confidence, decide_route, Route, load_config
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from backend.llm_fallback import LLMRequest, LLMResponse
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field


def _thresholds():
    cfg = load_config()["routing"]
    return cfg["low_confidence_threshold"], cfg["high_confidence_threshold"]


def run_text(text):
    ctx = PipelineContext("t", "t.txt", raw_text=text, source="test")
    runner.run(ctx)
    return ctx


@dataclass
class FakeCtx:
    raw_text: str = ""
    recruiter_output: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def _fake_ctx_with_event(event_id="e0", conf=0.5, org="Acme Corp",
                         title="Engineer", start="2020-01", end="2021-06"):
    return FakeCtx(
        raw_text="Engineer at Acme Corp Jan 2020 - Jun 2021. Built APIs.",
        recruiter_output={
            "status": "PARTIAL",
            "timeline": [{
                "id": event_id, "type": "EMPLOYMENT",
                "title": title, "org": org,
                "start": start, "end": end,
                "confidence": conf, "status": "CONFIRMED",
                "reasons": ["EVENT_EMPLOYMENT_CUES"],
                "source": {},
            }],
            "gaps": [],
        },
        meta={},
    )


def _mock_provider(corrected=None, confidence=0.8, changes=None,
                   available=True, side_effect=None):
    m = MagicMock()
    m.is_available.return_value = available
    if side_effect is not None:
        m.review.side_effect = side_effect
    else:
        m.review.return_value = LLMResponse(
            corrected_json=corrected or {}, confidence=confidence,
            changes_made=changes or [])
    return m


def test_high_confidence_auto_approve():
    """Resume with clear sections, explicit dates, no OCR."""
    low, high = _thresholds()
    resume = """
    John Doe
    Email: john.doe@example.com
    Phone: +1-555-123-4567

    EXPERIENCE
    Senior Engineer, Acme Corp, Jan 2020 - Present
    - Built APIs and microservices
    - Led team of 5 engineers
    - Improved system performance by 40%

    Software Engineer, Beta Inc, Jun 2017 - Dec 2019
    - Developed web applications
    - Wrote unit tests

    EDUCATION
    B.S. Computer Science, MIT, 2017
    """
    ctx = run_text(resume)
    decision = decide_route(ctx)

    assert decision.route == Route.AUTO_APPROVE
    assert decision.score >= high
    assert ctx.meta["routing"]["route"] == "auto_approve"


def test_medium_confidence_llm_review():
    """Score inside [low, high) routes to LLM review (mocked score)."""
    low, high = _thresholds()
    mid = (low + high) // 2
    with patch('backend.routing.compute_overall_confidence', return_value=mid):
        ctx = run_text("dummy")
        decision = decide_route(ctx)
        assert decision.route == Route.LLM_REVIEW
        assert low <= decision.score < high


def test_low_confidence_human_review():
    """Score below low threshold routes to human review (mocked score)."""
    low, high = _thresholds()
    with patch('backend.routing.compute_overall_confidence', return_value=low - 1):
        ctx = run_text("dummy")
        decision = decide_route(ctx)
        assert decision.route == Route.HUMAN_REVIEW
        assert decision.score < low


def test_score_below_40_never_calls_llm_provider():
    """Score < 40 must NEVER call the LLM provider, only human_review."""
    provider = MagicMock()
    with patch('backend.routing.compute_overall_confidence', return_value=35), \
         patch('backend.pipeline.runner.get_provider', return_value=provider):
        ctx = _fake_ctx_with_event()
        runner._apply_routing(ctx)
        assert ctx.meta["routing"]["route"] == "human_review"
        assert ctx.meta["routing"]["score"] == 35
        provider.review.assert_not_called()
        provider.is_available.assert_not_called()


def test_boundary_at_high():
    """Score exactly at high threshold → auto approve."""
    low, high = _thresholds()
    with patch('backend.routing.compute_overall_confidence', return_value=high):
        ctx = run_text("dummy")
        decision = decide_route(ctx)
        assert decision.route == Route.AUTO_APPROVE


def test_boundary_at_low():
    """Score exactly at low threshold → LLM review (not human)."""
    low, high = _thresholds()
    with patch('backend.routing.compute_overall_confidence', return_value=low):
        ctx = run_text("dummy")
        decision = decide_route(ctx)
        assert decision.route == Route.LLM_REVIEW


def test_llm_valid_correction_merged_and_revalidated():
    """a) Valid LLM correction is merged, tagged, re-validated."""
    low, high = _thresholds()
    mid = (low + high) // 2
    ctx = _fake_ctx_with_event(org="Acme Corp", title="",
                               start="2020-01", end="2021-06")
    corrected = {"timeline": [{
        "id": "e0", "type": "EMPLOYMENT",
        "title": "Engineer", "org": "Acme Corp",
        "start": "2020-01", "end": "2021-06",
    }]}
    provider = _mock_provider(corrected=corrected, changes=["e0.title: '' → 'Engineer'"])
    with patch('backend.routing.compute_overall_confidence', return_value=mid), \
         patch('backend.pipeline.runner.get_provider', return_value=provider):
        runner._apply_routing(ctx)
    assert ctx.meta["routing"]["route"] == "llm_review"
    assert ctx.meta["routing"]["llm_applied"] is True
    ev = ctx.recruiter_output["timeline"][0]
    assert ev["title"] == "Engineer"
    assert ev["provenance"]["title"] == "llm"
    applied = ctx.meta["routing"]["llm_changes"]
    assert applied[0]["old"] == "" and applied[0]["new"] == "Engineer"


def test_llm_hallucination_fails_validation_routes_to_human():
    """b) Hallucinated org/date fails validation → human review."""
    low, high = _thresholds()
    mid = (low + high) // 2
    ctx = _fake_ctx_with_event(org="Acme Corp", title="Engineer")
    corrected = {"timeline": [{
        "id": "e0", "type": "EMPLOYMENT",
        "title": "Engineer", "org": "Hallucinated Corp",
        "start": "1999-01", "end": "1999-06",
    }]}
    provider = _mock_provider(corrected=corrected)
    with patch('backend.routing.compute_overall_confidence', return_value=mid), \
         patch('backend.pipeline.runner.get_provider', return_value=provider):
        runner._apply_routing(ctx)
    assert ctx.meta["routing"]["route"] == "human_review"
    assert ctx.meta["routing"]["llm_validation_failed"] is True
    # Original untouched
    assert ctx.recruiter_output["timeline"][0]["org"] == "Acme Corp"


def test_llm_provider_raises_routes_to_human():
    """c) Provider exception → human review."""
    low, high = _thresholds()
    mid = (low + high) // 2
    ctx = _fake_ctx_with_event()
    provider = _mock_provider(side_effect=RuntimeError("boom"))
    with patch('backend.routing.compute_overall_confidence', return_value=mid), \
         patch('backend.pipeline.runner.get_provider', return_value=provider):
        runner._apply_routing(ctx)
    assert ctx.meta["routing"]["route"] == "human_review"
    assert "llm_error" in ctx.meta["routing"]


def test_default_provider_is_deepseek(monkeypatch):
    """Default config specifies deepseek provider in config/routing.yaml.

    is_available() checks for DEEPSEEK_API_KEY.
    """
    import os
    import yaml
    from pathlib import Path
    import backend.llm_fallback as F
    cfg = yaml.safe_load(
        (Path(__file__).parents[1] / "config" / "routing.yaml").read_text())
    assert cfg["llm"]["provider"] == "deepseek"
    F._provider_cache = None
    try:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        provider = F.get_provider()
        assert provider.is_available() is False

        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-123")
        assert provider.is_available() is True
    finally:
        F._provider_cache = None


def test_llm_unavailable_fallbacks_to_human():
    """d) Provider unavailable → human review."""
    low, high = _thresholds()
    mid = (low + high) // 2
    ctx = _fake_ctx_with_event()
    provider = _mock_provider(available=False)
    with patch('backend.routing.compute_overall_confidence', return_value=mid), \
         patch('backend.pipeline.runner.get_provider', return_value=provider):
        runner._apply_routing(ctx)
    assert ctx.meta["routing"]["route"] == "human_review"
    assert ctx.meta["routing"]["llm_unavailable"] is True


def test_bhargava_two_column_failure_detected_and_routes_to_review():
    """A.Bhargava.pdf has severe two-column layout extraction failures.

    Asserts confidence score detects failure signatures (score < 60),
    and routes to llm_review or human_review, NOT auto_approve.
    """
    from pathlib import Path
    from backend.routing import score_components

    pdf_path = Path(__file__).parents[1] / "dataset" / "test_samples" / "A.Bhargava.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Test fixture {pdf_path} not found")

    ctx = PipelineContext("bhargava", pdf_path.name, raw_bytes=pdf_path.read_bytes())
    runner.run(ctx)

    routing = ctx.meta.get("routing", {})
    decision_score = routing.get("score")
    route = routing.get("route")

    low, high = _thresholds()
    assert decision_score < high, f"Score {decision_score} should be < {high}"
    assert route in ("llm_review", "human_review"), f"Route {route} should not be auto_approve"
    assert route != "auto_approve"

    comps = score_components(ctx)
    assert comps["unlinked_entries"] > 0, "Should detect unlinked entries (empty org/title)"
    assert comps["unresolved_or_ambiguous"] > 0, "Should detect unresolved or ambiguous entries"


def test_sentence_fragment_detection_penalizes_score():
    """Sentence fragments as project/title names are detected and penalized."""
    from backend.routing import score_components, compute_overall_confidence
    ctx = _fake_ctx_with_event()
    ctx.recruiter_output["projects"] = [
        {"id": "p1", "name": ", banking, finance, and citizen service delivery, ensuring accura"}
    ]
    comps = score_components(ctx)
    assert comps["sentence_fragment_names"] > 0, "Should detect project sentence fragment name"
    score_with_frag = compute_overall_confidence(ctx)
    ctx.recruiter_output["projects"] = [
        {"id": "p1", "name": "Banking and Finance Reporting System"}
    ]
    score_without_frag = compute_overall_confidence(ctx)
    assert score_with_frag < score_without_frag, "Sentence fragment should reduce overall score"


def test_deepseek_strips_markdown_and_retries_on_json_failure():
    """DeepSeek stripping markdown fences and retrying with stricter prompt."""
    from backend.llm_providers.deepseek_provider import DeepSeekProvider, _strip_markdown_and_extract_json

    # Test markdown fence stripping
    s1 = "```json\n{\"corrected\": {\"timeline\": []}, \"confidence\": 0.85}\n```"
    assert _strip_markdown_and_extract_json(s1) == "{\"corrected\": {\"timeline\": []}, \"confidence\": 0.85}"

    provider = DeepSeekProvider({"api_key": "test-key"})
    req = LLMRequest(resume_text="test", extracted_json={}, low_confidence_fields=[], overall_score=50)

    calls = []
    def mock_call(prompt, sys_prompt, api_key):
        calls.append(sys_prompt)
        if len(calls) == 1:
            return "This is not valid json char 8123"
        return "```json\n{\"corrected\": {\"timeline\": []}, \"confidence\": 0.9}\n```"

    provider._call_api = mock_call
    res = provider.review(req)
    assert res.confidence == 0.9
    assert len(calls) == 2


def test_deepseek_fallback_to_human_when_retry_fails():
    """When DeepSeek fails parsing twice, runner falls back to human_review."""
    from backend.llm_providers.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider({"api_key": "test-key"})
    provider._call_api = lambda prompt, sys_prompt, api_key: "Still invalid json"

    low, high = _thresholds()
    mid = (low + high) // 2
    ctx = _fake_ctx_with_event()
    with patch("backend.routing.compute_overall_confidence", return_value=mid), \
         patch("backend.pipeline.runner.get_provider", return_value=provider):
        runner._apply_routing(ctx)
    assert ctx.meta["routing"]["route"] == "human_review"
    assert "DeepSeek JSON parse failed after retry" in ctx.meta["routing"]["llm_error"]


if __name__ == "__main__":
    test_high_confidence_auto_approve()
    print("✓ test_high_confidence_auto_approve")
    test_medium_confidence_llm_review()
    print("✓ test_medium_confidence_llm_review")
    test_low_confidence_human_review()
    print("✓ test_low_confidence_human_review")
    test_boundary_at_high()
    print("✓ test_boundary_at_high")
    test_boundary_at_low()
    print("✓ test_boundary_at_low")
    test_llm_valid_correction_merged_and_revalidated()
    print("✓ test_llm_valid_correction_merged_and_revalidated")
    test_llm_hallucination_fails_validation_routes_to_human()
    print("✓ test_llm_hallucination_fails_validation_routes_to_human")
    test_llm_provider_raises_routes_to_human()
    print("✓ test_llm_provider_raises_routes_to_human")
    test_llm_unavailable_fallbacks_to_human()
    print("✓ test_llm_unavailable_fallbacks_to_human")
    test_bhargava_two_column_failure_detected_and_routes_to_review()
    print("✓ test_bhargava_two_column_failure_detected_and_routes_to_review")
    print("\nAll tests passed!")
