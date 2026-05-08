"""Tests for the Executor."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.executor import Executor
from src.models import Task, TaskStatus, ToolResult
from src.state import StateManager
from src.tools import ToolRegistry


def make_task(task_id: str = "task-1") -> Task:
    return Task(id=task_id, description=f"Search for {task_id}", dependencies=[])


def make_result(task_id: str, success: bool = True) -> ToolResult:
    return ToolResult(
        tool_name="web_search",
        task_id=task_id,
        success=success,
        summary="Found results" if success else "Search failed",
        full_content="Content",
    )


@pytest.fixture
def state_and_session(tmp_path):
    db_path = tmp_path / "test.db"
    state = StateManager(str(db_path))
    from src.models import AgentSession
    session_id = "sess-1"
    state.create_session(AgentSession(session_id=session_id, goal="Test goal"))
    return state, session_id


# ---------------------------------------------------------------------------
# No tool available → task marked FAILED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_no_tool_marks_failed(state_and_session):
    state, session_id = state_and_session
    task = make_task()
    state.save_task(session_id, task)

    registry = ToolRegistry()  # empty — no tools registered
    executor = Executor(registry, state)

    result = await executor.execute_task(session_id, task, {})

    assert result.success is False
    assert "No tool available" in result.summary

    updated = state.get_task(session_id, task.id)
    assert updated.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Successful tool execution → task marked COMPLETED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_success_marks_completed(state_and_session):
    state, session_id = state_and_session
    task = make_task()
    state.save_task(session_id, task)

    # Create a mock tool
    from src.tools.base import Tool

    class FakeTool(Tool):
        @property
        def name(self) -> str:
            return "fake_tool"

        @property
        def description(self) -> str:
            return "A fake tool for testing"

        def can_handle(self, task: Task) -> bool:
            return True

        async def execute(self, task: Task, context: dict) -> ToolResult:
            return make_result(task.id, success=True)

    registry = ToolRegistry()
    registry.register(FakeTool())
    executor = Executor(registry, state)

    result = await executor.execute_task(session_id, task, {})

    assert result.success is True
    updated = state.get_task(session_id, task.id)
    assert updated.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Failed tool execution → task marked FAILED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_failure_marks_failed(state_and_session):
    state, session_id = state_and_session
    task = make_task()
    state.save_task(session_id, task)

    from src.tools.base import Tool

    class FailingTool(Tool):
        @property
        def name(self) -> str:
            return "failing_tool"

        @property
        def description(self) -> str:
            return "A failing tool for testing"

        def can_handle(self, task: Task) -> bool:
            return True

        async def execute(self, task: Task, context: dict) -> ToolResult:
            return make_result(task.id, success=False)

    registry = ToolRegistry()
    registry.register(FailingTool())
    executor = Executor(registry, state)

    result = await executor.execute_task(session_id, task, {})

    assert result.success is False
    updated = state.get_task(session_id, task.id)
    assert updated.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Tool result is persisted to state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_saves_tool_result(state_and_session):
    state, session_id = state_and_session
    task = make_task()
    state.save_task(session_id, task)

    from src.tools.base import Tool

    class FakeTool(Tool):
        @property
        def name(self) -> str:
            return "fake_tool"

        @property
        def description(self) -> str:
            return "A fake tool for testing"

        def can_handle(self, task: Task) -> bool:
            return True

        async def execute(self, task: Task, context: dict) -> ToolResult:
            return make_result(task.id)

    registry = ToolRegistry()
    registry.register(FakeTool())
    executor = Executor(registry, state)

    await executor.execute_task(session_id, task, {})

    saved_results = state.get_tool_results(session_id)
    assert len(saved_results) == 1
    assert saved_results[0].task_id == task.id
