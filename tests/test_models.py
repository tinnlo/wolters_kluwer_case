"""Tests for data models."""


from src.models import AgentSession, ResearchPlan, Task, TaskStatus, ToolResult


def test_task_creation():
    """Test creating a task."""
    task = Task(
        id="task-1",
        description="Search for WebAssembly adoption statistics",
        status=TaskStatus.PENDING,
        dependencies=[]
    )

    assert task.id == "task-1"
    assert task.status == TaskStatus.PENDING
    assert task.dependencies == []
    assert task.result is None


def test_research_plan_creation():
    """Test creating a research plan."""
    tasks = [
        Task(id="task-1", description="Task 1", dependencies=[]),
        Task(id="task-2", description="Task 2", dependencies=["task-1"]),
    ]

    plan = ResearchPlan(
        goal="Research WebAssembly",
        tasks=tasks
    )

    assert plan.goal == "Research WebAssembly"
    assert len(plan.tasks) == 2
    assert plan.tasks[1].dependencies == ["task-1"]


def test_tool_result_creation():
    """Test creating a tool result."""
    result = ToolResult(
        tool_name="web_search",
        task_id="task-1",
        success=True,
        summary="Found 5 relevant articles",
        full_content="Article 1...",
        metadata={"sources": ["url1", "url2"]}
    )

    assert result.tool_name == "web_search"
    assert result.success is True
    assert "sources" in result.metadata


def test_agent_session_creation():
    """Test creating an agent session."""
    session = AgentSession(
        session_id="session-123",
        goal="Research AI trends",
        status="planning"
    )

    assert session.session_id == "session-123"
    assert session.goal == "Research AI trends"
    assert session.status == "planning"
    assert session.plan is None
