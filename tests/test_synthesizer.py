"""Tests for the Synthesizer."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from src.synthesizer import Synthesizer
from src.models import ToolResult


def make_result(
    task_id: str,
    success: bool = True,
    content: str = "Some content",
    sources: list | None = None,
) -> ToolResult:
    if sources is None:
        sources = [{"url": f"https://example.com/{task_id}", "title": f"Source {task_id}"}]
    return ToolResult(
        tool_name="web_search",
        task_id=task_id,
        success=success,
        summary=f"Summary {task_id}",
        full_content=content,
        metadata={"sources": sources},
    )


def test_count_emitted_sources_standard():
    """Count numbered entries in a well-formed ## Sources section."""
    report = (
        "Body text.[1][2]\n\n"
        "## Sources\n\n"
        "  1 Site A — https://a.com\n"
        "  2 Site B — https://b.com\n"
        "  3 Site C — https://c.com\n"
    )
    assert Synthesizer._count_emitted_sources(report) == 3


def test_count_emitted_sources_no_section():
    """Returns 0 when no Sources section is present."""
    report = "Body text only.[1][2]"
    assert Synthesizer._count_emitted_sources(report) == 0


def test_count_emitted_sources_dot_style():
    """Handles '1. Title' numbered entries."""
    report = "Text.\n\n## Sources\n\n1. A\n2. B\n"
    assert Synthesizer._count_emitted_sources(report) == 2


def test_remove_out_of_range_citations_respects_emitted_count():
    """End-to-end: body citations beyond the emitted Sources count are stripped."""
    # Simulate a report where the LLM listed only 3 sources but cited [5] in the body
    report = (
        "Coinbase is safe.[1][3] Deriv has leverage.[5]\n\n"
        "## Sources\n\n"
        "  1 A — https://a.com\n"
        "  2 B — https://b.com\n"
        "  3 C — https://c.com\n"
    )
    emitted = Synthesizer._count_emitted_sources(report)
    result = Synthesizer._remove_out_of_range_citations(report, emitted)
    assert "[1]" in result
    assert "[3]" in result
    assert "[5]" not in result


# ---------------------------------------------------------------------------
# _remove_out_of_range_citations
# ---------------------------------------------------------------------------

def test_remove_out_of_range_citations_strips_excess():
    """Citations beyond source_count must be removed."""
    report = "Coinbase is safe.[1][5] Deriv has leverage.[20][21]"
    result = Synthesizer._remove_out_of_range_citations(report, source_count=5)
    assert "[1]" in result
    assert "[5]" in result
    assert "[20]" not in result
    assert "[21]" not in result


def test_remove_out_of_range_citations_keeps_all_valid():
    """All citations within range must be preserved unchanged."""
    report = "Finding A.[1] Finding B.[3] Finding C.[5]"
    result = Synthesizer._remove_out_of_range_citations(report, source_count=5)
    assert result == report


def test_remove_out_of_range_citations_empty_report():
    result = Synthesizer._remove_out_of_range_citations("", source_count=10)
    assert result == ""


def test_remove_out_of_range_citations_zero_source_count_strips_all():
    """When source_count=0 every [n] citation must be removed (no valid sources)."""
    report = "Report [1] contains findings [2] and more [3]."
    result = Synthesizer._remove_out_of_range_citations(report, source_count=0)
    assert "[1]" not in result
    assert "[2]" not in result
    assert "[3]" not in result
    assert "Report  contains findings  and more ." == result


# ---------------------------------------------------------------------------
# _strip_sources_section
# ---------------------------------------------------------------------------

def test_strip_sources_section_at_byte_zero():
    """A Sources heading at the very start of the string (no preceding newline)
    must still be stripped."""
    content = "## Sources\n1. https://example.com\n"
    result = Synthesizer._strip_sources_section(content)
    assert "Sources" not in result
    assert "https://example.com" not in result


def test_strip_sources_section_preserves_sources_of_revenue():
    """'## Sources of revenue' must NOT be stripped — it is not an exact match."""
    content = "Some text.\n\n## Sources of revenue\n\nMore text."
    result = Synthesizer._strip_sources_section(content)
    assert "Sources of revenue" in result


def test_strip_sources_section_with_preceding_newline():
    """A Sources heading preceded by a newline (normal case) is still stripped."""
    content = "Intro text.\n\n## Sources\n1. https://a.com\n"
    result = Synthesizer._strip_sources_section(content)
    assert "Sources" not in result
    assert "Intro text." in result


# ---------------------------------------------------------------------------
# synthesize (mocked API)
# ---------------------------------------------------------------------------

def test_build_context_contains_goal():
    synth = Synthesizer(api_key="test-key")
    ctx, _, _ = synth._build_context("My Goal", [make_result("t1")])
    assert "My Goal" in ctx


def test_build_context_contains_result_content():
    synth = Synthesizer(api_key="test-key")
    ctx, _, _ = synth._build_context("goal", [make_result("t1", content="Important finding")])
    assert "Important finding" in ctx


def test_build_context_marks_failed_results():
    synth = Synthesizer(api_key="test-key")
    ctx, _, _ = synth._build_context("goal", [make_result("t1", success=False)])
    assert "Failed" in ctx


def test_build_context_empty_results():
    synth = Synthesizer(api_key="test-key")
    ctx, count, _ = synth._build_context("goal", [])
    assert "0" in ctx  # "Total tasks completed: 0"
    assert count == 0


def test_build_context_source_count_matches_available_list():
    """The citation-count guard must match the actual number of unique sources."""
    synth = Synthesizer(api_key="test-key")
    r1 = make_result("t1", sources=[
        {"url": "https://a.com", "title": "A"},
        {"url": "https://b.com", "title": "B"},
    ])
    r2 = make_result("t2", sources=[
        {"url": "https://c.com", "title": "C"},
        {"url": "https://a.com", "title": "A"},  # duplicate — should be deduplicated
    ])
    ctx, count, _ = synth._build_context("goal", [r1, r2])
    # 3 unique sources (a, b, c)
    assert count == 3
    assert "exactly 3 entries" in ctx
    assert "[1] through [3]" in ctx


def test_build_context_strips_embedded_sources_section():
    """Embedded '## Sources' blocks must be removed from full_content."""
    content_with_sources = (
        "## AI Answer\nQuatum is cool.\n\n"
        "## Sources\n\n### 1. Wikipedia\nURL: https://en.wikipedia.org\nContent here.\n"
    )
    synth = Synthesizer(api_key="test-key")
    ctx, _, _ = synth._build_context("goal", [make_result("t1", content=content_with_sources)])
    # The local '### 1.' numbering must not appear in the synthesis context
    assert "### 1." not in ctx
    # But the AI answer body should still be there
    assert "Quatum is cool" in ctx


def test_build_context_uses_source_titles_from_metadata():
    """Source titles in the global list should come from metadata, not full_content."""
    synth = Synthesizer(api_key="test-key")
    r = make_result("t1", sources=[{"url": "https://real.com", "title": "Real Title"}])
    ctx, _, _ = synth._build_context("goal", [r])
    assert "Real Title" in ctx
    assert "https://real.com" in ctx


def test_build_context_strips_inline_citations_from_content():
    """Pre-existing [n] markers in full_content must not appear in synthesis context."""
    content_with_citations = "Nvidia leads [22] the market [23] as of 2026."
    synth = Synthesizer(api_key="test-key")
    ctx, _, _ = synth._build_context("goal", [make_result("t1", content=content_with_citations)])
    assert "[22]" not in ctx
    assert "[23]" not in ctx
    assert "Nvidia leads" in ctx


def test_build_context_no_sources_instructs_no_citations():
    """When no sources are available the prompt must tell the model not to cite."""
    synth = Synthesizer(api_key="test-key")
    result_no_sources = make_result("t1", sources=[])
    ctx, count, _ = synth._build_context("goal", [result_no_sources])
    assert count == 0
    # Must not emit a valid citation range
    assert "between 1 and" not in ctx
    # Must tell the model to omit citations
    assert "do NOT include" in ctx or "do not include" in ctx.lower()


def test_build_context_with_sources_does_not_say_no_citations():
    """When sources exist the no-citation instruction must not appear."""
    synth = Synthesizer(api_key="test-key")
    ctx, _, _ = synth._build_context("goal", [make_result("t1")])
    assert "do NOT include" not in ctx


@pytest.mark.asyncio
async def test_synthesize_raises_on_empty_response():
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = ""

    with patch("src.synthesizer.AsyncOpenAI") as mock_openai:
        mock_client = Mock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        synth = Synthesizer(api_key="test-key")
        with pytest.raises(ValueError, match="Empty response"):
            await synth.synthesize("goal", [make_result("t1")])


# ---------------------------------------------------------------------------
# Context Budget Tests
# ---------------------------------------------------------------------------

def test_budget_enforcement_with_small_budget():
    """With a small budget, full content should be truncated."""
    synth = Synthesizer(api_key="test-key", input_token_budget=2_000)

    # Create 10 results with large content
    results = []
    for i in range(10):
        large_content = "X" * 5000  # 5KB content
        results.append(make_result(f"t{i}", content=large_content))

    ctx, _, stats = synth._build_context("Test goal", results)

    # Budget enforcement: full content is truncated
    # With hard cap, not all results may be included
    assert stats.total_tokens <= 2_000  # Hard cap enforced
    # At least some results should be included
    assert stats.results_with_full_content + stats.results_summary_only >= 1
    # Most included results should be summary-only due to budget
    assert stats.results_summary_only >= stats.results_with_full_content
    # Truncation should have occurred
    assert stats.truncation_occurred


def test_budget_all_minimums_retained():
    """Tasks should be included while budget allows, then loop terminates."""
    synth = Synthesizer(api_key="test-key", input_token_budget=3_000)

    results = []
    for i in range(10):
        results.append(make_result(f"task-{i}", content="X" * 5000))

    ctx, _, stats = synth._build_context("Goal", results)

    # With hard cap, not all tasks may be included
    # Verify at least some task IDs appear in context
    included_count = sum(1 for i in range(10) if f"task-{i}" in ctx)
    assert included_count >= 1  # At least one task should fit
    assert included_count <= 10  # But not necessarily all
    # Verify tool name and status appear for included tasks
    assert "web_search" in ctx
    assert "Success" in ctx or "Failed" in ctx
    # Hard cap should be enforced
    assert stats.total_tokens <= 3_000


def test_budget_truncation_marker_present():
    """Truncation marker should appear when content is omitted."""
    synth = Synthesizer(api_key="test-key", input_token_budget=1_500)

    results = [make_result(f"t{i}", content="X" * 5000) for i in range(10)]
    ctx, _, stats = synth._build_context("Goal", results)

    if stats.results_summary_only > 0:
        assert "[Full content omitted due to synthesis budget]" in ctx


def test_budget_stats_counts_correct():
    """Stats should correctly count full vs summary-only results."""
    synth = Synthesizer(api_key="test-key", input_token_budget=3_000)

    results = [make_result(f"t{i}", content="X" * 5000) for i in range(10)]
    ctx, _, stats = synth._build_context("Goal", results)

    # With hard cap, not all results may be included
    total_included = stats.results_with_full_content + stats.results_summary_only
    assert total_included >= 1  # At least some results should fit
    assert total_included <= 10  # But not necessarily all
    # At least some should be summary-only due to budget
    assert stats.results_summary_only > 0
    # Hard cap enforced
    assert stats.total_tokens <= 3_000


def test_budget_summary_truncation_edge_case():
    """When summaries alone exceed budget, they should be truncated."""
    synth = Synthesizer(api_key="test-key", input_token_budget=1_500)

    # Create results with very long summaries
    results = []
    for i in range(10):
        result = make_result(f"t{i}", content="X" * 1000)
        # Override with long summary
        result.summary = "Y" * 1000  # 1KB summary
        results.append(result)

    ctx, _, stats = synth._build_context("Goal", results)

    # Hard cap should be enforced
    assert stats.total_tokens <= 1_500
    # Truncation should have occurred
    assert stats.truncation_occurred


def test_budget_with_generous_budget_no_truncation():
    """With a generous budget, no truncation should occur."""
    synth = Synthesizer(api_key="test-key", input_token_budget=100_000)

    results = [make_result(f"t{i}", content="Small content") for i in range(5)]
    ctx, _, stats = synth._build_context("Goal", results)

    # All should have full content
    assert stats.results_with_full_content == 5
    assert stats.results_summary_only == 0
    # No truncation needed
    assert not stats.truncation_occurred


def test_budget_fixed_cost_overflow():
    """When fixed costs exceed budget, synthesis should fail immediately."""
    import pytest

    synth = Synthesizer(api_key="test-key", input_token_budget=100)  # Tiny budget

    # Create many sources to inflate fixed costs
    results = []
    for i in range(50):
        result = make_result(f"t{i}", content="X" * 100)
        result.metadata = {"sources": [{"url": f"https://example.com/{i}", "title": f"Source {i}"}]}
        results.append(result)

    # Should raise ValueError when fixed costs exceed budget
    with pytest.raises(ValueError, match="Synthesis budget.*insufficient"):
        synth._build_context("Goal", results)


def test_budget_hard_cap_with_source_heavy_results():
    """Regression test: sources added after result selection must not push us over budget."""
    # This test catches the bug where result selection uses estimated instruction tokens (200),
    # but actual instruction tokens depend on source count, causing overflow.
    synth = Synthesizer(api_key="test-key", input_token_budget=2_000)

    # Create 10 results, each with 5 sources (50 sources total)
    results = []
    for i in range(10):
        result = make_result(f"task-{i}", content="X" * 1000)
        result.metadata = {
            "sources": [
                {"url": f"https://example.com/{i}-{j}", "title": f"Source {i}-{j}"}
                for j in range(5)
            ]
        }
        results.append(result)

    ctx, source_count, stats = synth._build_context("Research goal", results)

    # HARD CAP: total tokens must not exceed budget
    assert stats.total_tokens <= 2_000, (
        f"Hard cap violated: {stats.total_tokens} tokens > {2_000} budget"
    )

    # At least some results should be included
    included = stats.results_with_full_content + stats.results_summary_only
    assert included >= 1, "At least one result should fit in budget"

    # Count how many task IDs actually appear in the context
    included_task_ids = [i for i in range(10) if f"task-{i}" in ctx]

    # Stats should match actual included count
    assert len(included_task_ids) == included, (
        f"Stats report {included} included but context has {len(included_task_ids)} task IDs"
    )

    # If results have sources, source section must exist and be non-empty
    if included > 0:
        assert source_count > 0, "Included results have sources but source_count is 0"
        assert "# Available Sources" in ctx or "# Sources" in ctx, (
            "Included results have sources but no source section in context"
        )


def test_build_context_sources_only_for_included_blocks():
    """The global source list must only include sources from included result blocks."""
    synth = Synthesizer(api_key="test-key", input_token_budget=1_500)
    included = make_result(
        "included",
        content="short content",
        sources=[{"url": "https://included.example", "title": "Included"}],
    )
    omitted = make_result(
        "omitted",
        content="short content",
        sources=[
            {
                "url": f"https://omitted.example/{i}",
                "title": f"Omitted {i}",
            }
                for i in range(200)
            ],
        )

    ctx, source_count, stats = synth._build_context("Goal", [included, omitted])

    assert stats.total_tokens <= 1_500
    assert source_count == 1
    assert "https://included.example" in ctx
    assert "https://omitted.example/0" not in ctx


def test_budget_hard_cap_with_many_source_heavy_results():
    """Regression test: trim loop must recalculate fixed_tokens to avoid over-trimming."""
    # This test catches the bug where fixed_tokens is calculated once before the trim loop,
    # causing the loop to trim against stale source costs and potentially drop all results.
    synth = Synthesizer(api_key="test-key", input_token_budget=3_000)

    # Create 20 results, each with 5KB content and 5 sources
    results = []
    for i in range(20):
        result = make_result(f"task-{i}", content="X" * 5000)
        result.metadata = {
            "sources": [
                {"url": f"https://example.com/{i}-{j}", "title": f"Source {i}-{j}"}
                for j in range(5)
            ]
        }
        results.append(result)

    # Should not raise ValueError - a smaller subset should fit
    ctx, source_count, stats = synth._build_context("Research goal", results)

    # HARD CAP: total tokens must not exceed budget
    assert stats.total_tokens <= 3_000, (
        f"Hard cap violated: {stats.total_tokens} tokens > {3_000} budget"
    )

    # At least one result should be included (not trimmed to zero)
    included = stats.results_with_full_content + stats.results_summary_only
    assert included > 0, "Trim loop over-trimmed: no results included when a subset should fit"

    # Source section must exist since included results have sources
    assert source_count > 0, "Included results have sources but source_count is 0"
    assert "# Available Sources" in ctx, "Source section missing despite included results having sources"
