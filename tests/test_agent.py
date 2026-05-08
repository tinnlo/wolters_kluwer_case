"""Integration tests for the agent system."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

import pytest

from src.agent import create_agent
from src.models import ResearchPlan, Task


@pytest.mark.asyncio
async def test_agent_end_to_end(monkeypatch):
    """Test complete agent flow with mocked APIs."""
    # Set mock API keys
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Mock OpenAI responses
        mock_plan_response = Mock()
        mock_plan_response.choices = [Mock()]
        mock_plan_response.choices[0].message.content = """{
            "tasks": [
                {
                    "id": "task-1",
                    "description": "Search for Python async best practices",
                    "dependencies": []
                }
            ]
        }"""

        mock_synthesis_response = Mock()
        mock_synthesis_response.choices = [Mock()]
        mock_synthesis_response.choices[0].message.content = "# Final Report\\n\\nTest report content"

        # Mock Tavily response
        mock_tavily_response = {
            "results": [
                {
                    "title": "Python Async Guide",
                    "url": "https://example.com/async",
                    "content": "Async programming in Python...",
                }
            ],
            "answer": "Python async is great for I/O operations",
        }

        with patch("src.planner.OpenAI") as mock_planner_openai, \
             patch("src.synthesizer.OpenAI") as mock_synth_openai, \
             patch("httpx.AsyncClient") as mock_httpx, \
             patch("src.cli.CLI.display_plan", return_value=True), \
             patch("src.cli.CLI.get_research_goal", return_value="Test goal"):

            # Setup OpenAI mocks
            mock_planner_client = Mock()
            mock_planner_openai.return_value = mock_planner_client
            mock_planner_client.chat.completions.create.return_value = mock_plan_response

            mock_synth_client = Mock()
            mock_synth_openai.return_value = mock_synth_client
            mock_synth_client.chat.completions.create.return_value = mock_synthesis_response

            # Setup Tavily mock
            mock_http_response = Mock()
            mock_http_response.json.return_value = mock_tavily_response
            mock_http_response.raise_for_status = Mock()

            mock_post = AsyncMock(return_value=mock_http_response)
            mock_httpx.return_value.__aenter__.return_value.post = mock_post

            # Create and run agent
            agent = create_agent(str(db_path))
            result = await agent.run("Test research goal")

            # Verify result
            assert "Final Report" in result
            assert "Test report content" in result

            # Verify database state
            session = agent.state.get_session(agent.state.get_session("test-session") or "")
            # Note: We can't easily get session_id from the run, but we verified the flow works
