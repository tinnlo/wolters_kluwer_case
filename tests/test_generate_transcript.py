"""Tests for transcript generation helpers."""

from generate_transcript import _count_unique_source_urls
from src.models import ToolResult


def test_count_unique_source_urls_deduplicates_metadata_urls():
    """Transcript source counting should deduplicate URLs from metadata sources."""
    results = [
        ToolResult(
            tool_name="web_search",
            task_id="task-1",
            success=True,
            summary="done",
            full_content="",
            metadata={"sources": [{"url": "https://one.example"}, {"url": "https://two.example"}]},
        ),
        ToolResult(
            tool_name="web_search",
            task_id="task-2",
            success=True,
            summary="done",
            full_content="",
            metadata={"sources": ["https://two.example", "https://three.example"]},
        ),
    ]

    # Should deduplicate: one, two (from task-1), two (duplicate), three (from task-2) = 3 unique
    assert _count_unique_source_urls(results) == 3


def test_count_unique_source_urls_excludes_failed_results():
    """Regression: failed results should not contribute to source count."""
    results = [
        ToolResult(
            tool_name="web_search",
            task_id="task-1",
            success=True,
            summary="done",
            full_content="",
            metadata={"sources": [{"url": "https://one.example"}]},
        ),
        ToolResult(
            tool_name="web_search",
            task_id="task-2",
            success=False,  # Failed result
            summary="error",
            full_content="",
            error="API error",
            metadata={"sources": [{"url": "https://two.example"}, {"url": "https://three.example"}]},
        ),
    ]

    # Should only count sources from successful results: 1 (not 3)
    assert _count_unique_source_urls(results) == 1
