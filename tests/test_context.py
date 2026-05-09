"""Tests for the ContextManager."""


from src.context import ContextManager
from src.models import Task, TaskStatus, ToolResult


def make_result(task_id: str, success: bool = True) -> ToolResult:
    return ToolResult(
        tool_name="web_search",
        task_id=task_id,
        success=success,
        summary=f"Summary for {task_id}",
        full_content=f"Content for {task_id}",
    )


def make_task(task_id: str, status: TaskStatus = TaskStatus.PENDING) -> Task:
    t = Task(id=task_id, description=f"Task {task_id}", dependencies=[])
    t.status = status
    return t


# ---------------------------------------------------------------------------
# add_result / rolling window
# ---------------------------------------------------------------------------

def test_add_result_stores_result():
    ctx = ContextManager(max_recent_results=5)
    ctx.add_result(make_result("t1"))
    assert len(ctx._recent_results) == 1


def test_add_result_rolling_window():
    """Results beyond max_recent_results are dropped from the front."""
    ctx = ContextManager(max_recent_results=3)
    for i in range(5):
        ctx.add_result(make_result(f"t{i}"))

    assert len(ctx._recent_results) == 3
    # Should keep the last 3
    assert ctx._recent_results[0].task_id == "t2"
    assert ctx._recent_results[-1].task_id == "t4"


def test_add_result_exactly_at_limit():
    ctx = ContextManager(max_recent_results=2)
    ctx.add_result(make_result("t1"))
    ctx.add_result(make_result("t2"))
    assert len(ctx._recent_results) == 2


# ---------------------------------------------------------------------------
# get_context_for_task
# ---------------------------------------------------------------------------

def test_get_context_for_task_contains_goal():
    ctx = ContextManager()
    task = make_task("task-1")
    result = ctx.get_context_for_task("My Goal", task, [task])
    assert result["goal"] == "My Goal"


def test_get_context_for_task_contains_current_task():
    ctx = ContextManager()
    task = make_task("task-1")
    result = ctx.get_context_for_task("goal", task, [task])
    assert result["current_task"]["id"] == "task-1"


def test_get_context_for_task_includes_recent_results():
    ctx = ContextManager()
    ctx.add_result(make_result("t0"))
    task = make_task("task-1")
    result = ctx.get_context_for_task("goal", task, [task])
    assert "t0" in result["recent_results"]


def test_get_context_for_task_empty_recent_results():
    ctx = ContextManager()
    task = make_task("task-1")
    result = ctx.get_context_for_task("goal", task, [task])
    assert "No recent results" in result["recent_results"]


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------

def test_clear_removes_all_results():
    ctx = ContextManager()
    ctx.add_result(make_result("t1"))
    ctx.add_result(make_result("t2"))
    ctx.clear()
    assert ctx._recent_results == []
