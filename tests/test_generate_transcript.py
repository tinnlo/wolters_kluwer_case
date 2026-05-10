"""Tests for transcript generation helpers."""

import sys
from unittest.mock import MagicMock, patch

from generate_transcript import _count_unique_source_urls
from src.models import AgentSession, ToolResult


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


def test_main_anchors_output_path_to_repo_root_with_goal(tmp_path, monkeypatch):
    """Regression: main() should anchor output path to REPO_ROOT, not CWD."""
    # Simulate running from outside the repo
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    monkeypatch.chdir(outside_dir)

    # Mock REPO_ROOT to point to a fake repo
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()

    # Mock StateManager to return a session with a goal
    fake_session = AgentSession(
        session_id="test-session-123",
        goal="Test security best practices",
    )
    mock_state = MagicMock()
    mock_state.get_session.return_value = fake_session

    # Patch sys.argv to simulate CLI invocation without output path
    monkeypatch.setattr(sys, "argv", ["generate_transcript.py", "test-session-123"])

    # Patch dependencies
    with patch("src.generate_transcript.REPO_ROOT", fake_repo):
        with patch("src.generate_transcript.StateManager", return_value=mock_state):
            with patch("src.generate_transcript.generate_transcript") as mock_generate:
                from src.generate_transcript import main

                main()

                # Verify generate_transcript was called with repo-anchored path
                mock_generate.assert_called_once()
                output_path = mock_generate.call_args[0][1]
                assert output_path.startswith(str(fake_repo / "examples"))
                assert "transcript_test_security_best_practices.md" in output_path


def test_main_anchors_output_path_to_repo_root_without_goal(tmp_path, monkeypatch):
    """Regression: main() should fall back to session ID when goal is missing."""
    # Simulate running from outside the repo
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    monkeypatch.chdir(outside_dir)

    # Mock REPO_ROOT to point to a fake repo
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()

    # Mock StateManager to return a session without a goal
    fake_session = AgentSession(
        session_id="test-session-456",
        goal="",  # Empty goal
    )
    mock_state = MagicMock()
    mock_state.get_session.return_value = fake_session

    # Patch sys.argv to simulate CLI invocation without output path
    monkeypatch.setattr(sys, "argv", ["generate_transcript.py", "test-session-456"])

    # Patch dependencies
    with patch("src.generate_transcript.REPO_ROOT", fake_repo):
        with patch("src.generate_transcript.StateManager", return_value=mock_state):
            with patch("src.generate_transcript.generate_transcript") as mock_generate:
                from src.generate_transcript import main

                main()

                # Verify generate_transcript was called with repo-anchored path using session ID
                mock_generate.assert_called_once()
                output_path = mock_generate.call_args[0][1]
                assert output_path.startswith(str(fake_repo / "examples"))
                assert "transcript_test_session_456.md" in output_path
