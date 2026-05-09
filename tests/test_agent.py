"""Integration tests for the agent system."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

import pytest

from src.agent import create_agent
from src.models import AgentSession, ResearchPlan, SessionStatus, Task, TaskStatus, ToolResult


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

        with patch("src.planner.AsyncOpenAI") as mock_planner_openai, \
             patch("src.synthesizer.AsyncOpenAI") as mock_synth_openai, \
             patch("httpx.AsyncClient") as mock_httpx, \
             patch("src.cli.CLI.display_plan", return_value=(True, None)), \
             patch("src.cli.CLI.get_research_goal", return_value="Test goal"):

            # Setup OpenAI mocks (AsyncOpenAI — create must be an AsyncMock)
            mock_planner_client = Mock()
            mock_planner_openai.return_value = mock_planner_client
            mock_planner_client.chat.completions.create = AsyncMock(
                return_value=mock_plan_response
            )

            mock_synth_client = Mock()
            mock_synth_openai.return_value = mock_synth_client
            mock_synth_client.chat.completions.create = AsyncMock(
                return_value=mock_synthesis_response
            )

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

            # Verify the session was persisted — list_sessions returns at least one entry
            sessions = agent.state.list_sessions()
            assert len(sessions) >= 1


# ---------------------------------------------------------------------------
# Resume guard tests
# ---------------------------------------------------------------------------

def _make_agent(tmpdir):
    """Create an agent with an isolated DB; no API keys needed."""
    import os
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    os.environ.setdefault("TAVILY_API_KEY", "test-key")
    db_path = Path(tmpdir) / "test.db"
    with patch("src.planner.AsyncOpenAI"), patch("src.synthesizer.AsyncOpenAI"):
        return create_agent(str(db_path))


def _seed_session(agent, status: SessionStatus) -> str:
    """Insert a minimal session with one pending task into the DB."""
    import uuid
    session_id = str(uuid.uuid4())
    session = AgentSession(session_id=session_id, goal="test goal", status=status)
    agent.state.create_session(session)
    task = Task(id="task-1", description="do something", dependencies=[])
    agent.state.save_task(session_id, task)
    return session_id


@pytest.mark.asyncio
async def test_resume_rejects_cancelled_session():
    """resume() must raise ValueError for CANCELLED sessions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _make_agent(tmpdir)
        session_id = _seed_session(agent, SessionStatus.CANCELLED)
        with pytest.raises(ValueError, match="was cancelled by the user"):
            await agent.resume(session_id)


@pytest.mark.asyncio
async def test_resume_allows_planning_session():
    """resume() can now resume PLANNING sessions to continue plan refinement."""
    # This test just verifies that PLANNING sessions don't raise ValueError anymore
    # Full integration testing would require mocking user input which is complex
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _make_agent(tmpdir)
        session_id = _seed_session(agent, SessionStatus.PLANNING)

        # Store a plan in the session
        test_plan = ResearchPlan(
            goal="test goal",
            tasks=[Task(id="task-1", description="test task", dependencies=[])]
        )
        agent.state.update_session(session_id, plan=test_plan)
        agent.state.save_task(session_id, test_plan.tasks[0])

        # Verify that calling resume doesn't raise ValueError for PLANNING status
        # We'll mock display_plan to immediately approve and avoid hanging
        with patch.object(agent.cli, 'show_info'), \
             patch.object(agent.cli, 'show_warning'), \
             patch.object(agent.cli, 'display_plan') as mock_display:

            # Simulate user rejecting without feedback to trigger early return
            mock_display.return_value = (False, None)

            result = await agent.resume(session_id)

            # Should return cancellation message, not raise ValueError
            assert "cancelled" in result.lower()


@pytest.mark.asyncio
async def test_resume_rejects_completed_session():
    """resume() must raise ValueError for COMPLETED sessions (existing behaviour)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _make_agent(tmpdir)
        session_id = _seed_session(agent, SessionStatus.COMPLETED)
        with pytest.raises(ValueError, match="already completed"):
            await agent.resume(session_id)


@pytest.mark.asyncio
async def test_resume_resets_failed_tasks_and_executes():
    """resume() must reset FAILED tasks to PENDING and then execute them."""
    import uuid
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _make_agent(tmpdir)

        # Seed a FAILED session with one FAILED task
        session_id = str(uuid.uuid4())
        session = AgentSession(session_id=session_id, goal="test goal", status=SessionStatus.FAILED)
        agent.state.create_session(session)
        task = Task(id="task-1", description="do something", dependencies=[])
        agent.state.save_task(session_id, task)
        agent.state.update_task_status(session_id, "task-1", TaskStatus.FAILED, error="network error")

        # Precondition: task is FAILED before resume
        assert agent.state.get_task(session_id, "task-1").status == TaskStatus.FAILED

        mock_result = ToolResult(
            tool_name="web_search",
            task_id="task-1",
            success=True,
            summary="done",
            full_content="content",
            metadata={"sources": []},
        )

        # Side effect marks the task COMPLETED in state (as the real executor would)
        # so that has_pending_tasks() returns False and the loop terminates.
        async def fake_execute(sid, t, ctx):
            agent.state.update_task_status(sid, t.id, TaskStatus.COMPLETED)
            agent.state.save_tool_result(sid, mock_result)
            return mock_result

        agent.executor.execute_task = fake_execute
        agent.synthesizer.synthesize = AsyncMock(return_value="# Report\n\nDone.")

        await agent.resume(session_id)

        # Synthesizer must have been called — confirms the failed task was retried
        # and produced a result that flowed through to synthesis.
        agent.synthesizer.synthesize.assert_called_once()
        synthesize_args = agent.synthesizer.synthesize.call_args[0]
        # First arg is goal, second is list of ToolResult
        assert any(r.task_id == "task-1" for r in synthesize_args[1])


@pytest.mark.asyncio
async def test_resume_planning_refinement_replaces_stale_tasks():
    """Refining a resumed planning session should replace rejected-plan tasks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _make_agent(tmpdir)
        session_id = _seed_session(agent, SessionStatus.PLANNING)
        original_plan = ResearchPlan(
            goal="test goal",
            tasks=[Task(id="stale-task", description="stale", dependencies=[])],
        )
        agent.state.update_session(session_id, plan=original_plan)
        agent.state.replace_session_tasks(session_id, original_plan.tasks)

        refined_plan = ResearchPlan(
            goal="test goal",
            tasks=[Task(id="fresh-task", description="fresh", dependencies=[])],
        )
        agent.planner.create_plan = AsyncMock(return_value=refined_plan)

        with patch.object(agent.cli, "display_plan", side_effect=[(False, "refine it"), (True, None)]), \
             patch.object(agent.cli, "show_info"), \
             patch.object(agent.cli, "show_warning"), \
             patch.object(agent.cli, "display_final_report"), \
             patch.object(agent.cli, "show_session_summary"):
            async def fake_execute(sid, current_task, ctx):
                agent.state.update_task_status(sid, current_task.id, TaskStatus.COMPLETED)
                result = ToolResult(
                    tool_name="web_search",
                    task_id=current_task.id,
                    success=True,
                    summary="done",
                    full_content="content",
                    metadata={"sources": []},
                )
                agent.state.save_tool_result(sid, result)
                return result

            agent.executor.execute_task = fake_execute
            agent.synthesizer.synthesize = AsyncMock(return_value="# Report\n\nDone.")

            await agent.resume(session_id)

        task_ids = {task.id for task in agent.state.get_session_tasks(session_id)}
        assert task_ids == {"fresh-task"}
        assert agent.state.get_task(session_id, "stale-task") is None


@pytest.mark.asyncio
async def test_resume_retry_deletes_stale_tool_results_before_retry():
    """Retryable resumes should remove old task results before saving the retry result."""
    import uuid

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _make_agent(tmpdir)
        session_id = str(uuid.uuid4())
        session = AgentSession(session_id=session_id, goal="test goal", status=SessionStatus.FAILED)
        agent.state.create_session(session)
        task = Task(id="task-1", description="do something", dependencies=[])
        agent.state.save_task(session_id, task)
        agent.state.update_task_status(session_id, "task-1", TaskStatus.FAILED, error="network error")
        agent.state.save_tool_result(
            session_id,
            ToolResult(
                tool_name="web_search",
                task_id="task-1",
                success=True,
                summary="stale",
                full_content="stale content",
                metadata={"sources": [{"url": "https://stale.example"}]},
            ),
        )

        async def fake_execute(sid, current_task, ctx):
            existing = agent.state.get_tool_results(sid)
            assert [result.summary for result in existing] == []
            agent.state.update_task_status(sid, current_task.id, TaskStatus.COMPLETED)
            fresh = ToolResult(
                tool_name="web_search",
                task_id=current_task.id,
                success=True,
                summary="fresh",
                full_content="fresh content",
                metadata={"sources": [{"url": "https://fresh.example"}]},
            )
            agent.state.save_tool_result(sid, fresh)
            return fresh

        agent.executor.execute_task = fake_execute
        agent.synthesizer.synthesize = AsyncMock(return_value="# Report\n\nDone.")

        await agent.resume(session_id)

        results = agent.state.get_tool_results(session_id)
        assert len(results) == 1
        assert results[0].summary == "fresh"
