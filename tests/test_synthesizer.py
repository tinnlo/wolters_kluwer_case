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
    ctx, _ = synth._build_context("My Goal", [make_result("t1")])
    assert "My Goal" in ctx


def test_build_context_contains_result_content():
    synth = Synthesizer(api_key="test-key")
    ctx, _ = synth._build_context("goal", [make_result("t1", content="Important finding")])
    assert "Important finding" in ctx


def test_build_context_marks_failed_results():
    synth = Synthesizer(api_key="test-key")
    ctx, _ = synth._build_context("goal", [make_result("t1", success=False)])
    assert "Failed" in ctx


def test_build_context_empty_results():
    synth = Synthesizer(api_key="test-key")
    ctx, count = synth._build_context("goal", [])
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
    ctx, count = synth._build_context("goal", [r1, r2])
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
    ctx, _ = synth._build_context("goal", [make_result("t1", content=content_with_sources)])
    # The local '### 1.' numbering must not appear in the synthesis context
    assert "### 1." not in ctx
    # But the AI answer body should still be there
    assert "Quatum is cool" in ctx


def test_build_context_uses_source_titles_from_metadata():
    """Source titles in the global list should come from metadata, not full_content."""
    synth = Synthesizer(api_key="test-key")
    r = make_result("t1", sources=[{"url": "https://real.com", "title": "Real Title"}])
    ctx, _ = synth._build_context("goal", [r])
    assert "Real Title" in ctx
    assert "https://real.com" in ctx


def test_build_context_strips_inline_citations_from_content():
    """Pre-existing [n] markers in full_content must not appear in synthesis context."""
    content_with_citations = "Nvidia leads [22] the market [23] as of 2026."
    synth = Synthesizer(api_key="test-key")
    ctx, _ = synth._build_context("goal", [make_result("t1", content=content_with_citations)])
    assert "[22]" not in ctx
    assert "[23]" not in ctx
    assert "Nvidia leads" in ctx


def test_build_context_no_sources_instructs_no_citations():
    """When no sources are available the prompt must tell the model not to cite."""
    synth = Synthesizer(api_key="test-key")
    result_no_sources = make_result("t1", sources=[])
    ctx, count = synth._build_context("goal", [result_no_sources])
    assert count == 0
    # Must not emit a valid citation range
    assert "between 1 and" not in ctx
    # Must tell the model to omit citations
    assert "do NOT include" in ctx or "do not include" in ctx.lower()


def test_build_context_with_sources_does_not_say_no_citations():
    """When sources exist the no-citation instruction must not appear."""
    synth = Synthesizer(api_key="test-key")
    ctx, _ = synth._build_context("goal", [make_result("t1")])
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
