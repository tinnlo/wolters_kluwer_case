"""Tests for state management."""

import tempfile
from pathlib import Path

from src.models import AgentSession, Task, TaskStatus, ToolResult
from src.state import StateManager


def test_state_manager_init():
    """Test state manager initialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        StateManager(str(db_path))

        assert db_path.exists()


def test_create_and_get_session():
    """Test creating and retrieving a session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        state = StateManager(str(db_path))

        session = AgentSession(
            session_id="test-session",
            goal="Test research goal",
            status="planning"
        )

        state.create_session(session)
        retrieved = state.get_session("test-session")

        assert retrieved is not None
        assert retrieved.session_id == "test-session"
        assert retrieved.goal == "Test research goal"


def test_save_and_get_task():
    """Test saving and retrieving tasks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        state = StateManager(str(db_path))

        # Create session first
        session = AgentSession(
            session_id="test-session",
            goal="Test goal",
            status="planning"
        )
        state.create_session(session)

        # Create and save task
        task = Task(
            id="task-1",
            description="Test task",
            status=TaskStatus.PENDING,
            dependencies=[]
        )
        state.save_task("test-session", task)

        # Retrieve task
        retrieved = state.get_task("test-session", "task-1")
        assert retrieved is not None
        assert retrieved.id == "task-1"
        assert retrieved.description == "Test task"


def test_get_next_task_with_dependencies():
    """Test getting next task respecting dependencies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        state = StateManager(str(db_path))

        # Create session
        session = AgentSession(
            session_id="test-session",
            goal="Test goal",
            status="executing"
        )
        state.create_session(session)

        # Create tasks with dependencies
        task1 = Task(id="task-1", description="Task 1", dependencies=[])
        task2 = Task(id="task-2", description="Task 2", dependencies=["task-1"])

        state.save_task("test-session", task1)
        state.save_task("test-session", task2)

        # Should get task-1 first (no dependencies)
        next_task = state.get_next_task("test-session")
        assert next_task is not None
        assert next_task.id == "task-1"

        # Complete task-1
        state.update_task_status("test-session", "task-1", TaskStatus.COMPLETED, result="Done")

        # Now should get task-2
        next_task = state.get_next_task("test-session")
        assert next_task is not None
        assert next_task.id == "task-2"


def test_save_tool_result():
    """Test saving tool results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        state = StateManager(str(db_path))

        # Create session
        session = AgentSession(
            session_id="test-session",
            goal="Test goal",
            status="executing"
        )
        state.create_session(session)

        # Save tool result
        result = ToolResult(
            tool_name="web_search",
            task_id="task-1",
            success=True,
            summary="Found results",
            full_content="Full content here",
            metadata={"count": 5}
        )
        state.save_tool_result("test-session", result)

        # Retrieve results
        results = state.get_tool_results("test-session")
        assert len(results) == 1
        assert results[0].tool_name == "web_search"
        assert results[0].success is True


def test_delete_tool_results_for_task():
    """Deleting results for a task must not affect results for other tasks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        state = StateManager(str(db_path))

        session = AgentSession(
            session_id="test-session",
            goal="Test goal",
            status="executing",
        )
        state.create_session(session)

        def _make_result(task_id: str) -> ToolResult:
            return ToolResult(
                tool_name="web_search",
                task_id=task_id,
                success=True,
                summary=f"Summary {task_id}",
                full_content=f"Content {task_id}",
                metadata={},
            )

        state.save_tool_result("test-session", _make_result("task-1"))
        state.save_tool_result("test-session", _make_result("task-2"))

        # Delete results for task-1 only
        state.delete_tool_results_for_task("test-session", "task-1")

        results = state.get_tool_results("test-session")
        assert len(results) == 1
        assert results[0].task_id == "task-2"


def test_replace_session_tasks():
    """Test replacing all tasks for a session removes stale tasks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        state = StateManager(str(db_path))

        # Create session
        session = AgentSession(
            session_id="test-session",
            goal="Test goal",
            status="planning"
        )
        state.create_session(session)

        # Save initial tasks
        task1 = Task(id="task-1", description="Task 1", dependencies=[])
        task2 = Task(id="task-2", description="Task 2", dependencies=[])
        task3 = Task(id="task-3", description="Task 3", dependencies=[])

        state.save_task("test-session", task1)
        state.save_task("test-session", task2)
        state.save_task("test-session", task3)

        # Verify all 3 tasks exist
        tasks = state.get_session_tasks("test-session")
        assert len(tasks) == 3
        assert {t.id for t in tasks} == {"task-1", "task-2", "task-3"}

        # Replace with new task list (task-2 removed, task-4 added)
        new_task1 = Task(id="task-1", description="Task 1 updated", dependencies=[])
        new_task3 = Task(id="task-3", description="Task 3 updated", dependencies=[])
        new_task4 = Task(id="task-4", description="Task 4", dependencies=[])

        state.replace_session_tasks("test-session", [new_task1, new_task3, new_task4])

        # Verify task-2 is gone and task-4 is present
        tasks = state.get_session_tasks("test-session")
        assert len(tasks) == 3
        assert {t.id for t in tasks} == {"task-1", "task-3", "task-4"}

        # Verify descriptions were updated
        task1_retrieved = state.get_task("test-session", "task-1")
        assert task1_retrieved is not None
        assert task1_retrieved.description == "Task 1 updated"

        # Verify task-2 is truly gone
        task2_retrieved = state.get_task("test-session", "task-2")
        assert task2_retrieved is None
