"""Context management for maintaining conversation state."""

from typing import Any

import tiktoken

from .models import Task, ToolResult


def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """Estimate token count for text using tiktoken.

    Args:
        text: Text to estimate tokens for
        model: Model name for tokenizer (default: gpt-4)

    Returns:
        Estimated token count (minimum 1 for non-empty text)
    """
    if not text:
        return 0
    try:
        # Normalize model names to tiktoken-compatible identifiers
        # gpt-5.x and gpt-4o use o200k_base encoding
        if model.startswith("gpt-5") or model.startswith("gpt-4o"):
            encoding = tiktoken.get_encoding("o200k_base")
        else:
            encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except Exception:
        # Fallback to heuristic if tiktoken fails
        return max(1, len(text) // 4)


class ContextManager:
    """Manages context for LLM prompts to avoid token overflow."""

    def __init__(self, max_recent_results: int = 5):
        """Initialize context manager.

        Args:
            max_recent_results: Maximum number of recent results to keep in context
        """
        self.max_recent_results = max_recent_results
        self._recent_results: list[ToolResult] = []

    def add_result(self, result: ToolResult) -> None:
        """Add a tool result to recent context.

        Args:
            result: The tool result to add
        """
        self._recent_results.append(result)

        # Keep only recent results
        if len(self._recent_results) > self.max_recent_results:
            self._recent_results = self._recent_results[-self.max_recent_results:]

    def get_context_for_task(
        self, goal: str, current_task: Task, all_tasks: list[Task]
    ) -> dict[str, Any]:
        """Build context for executing a task.

        Args:
            goal: The research goal
            current_task: The task being executed
            all_tasks: All tasks in the plan

        Returns:
            Context dictionary for the executor
        """
        # Build task summary
        task_summary = self._build_task_summary(all_tasks)

        # Build recent results summary
        recent_results_summary = self._build_results_summary()

        return {
            "goal": goal,
            "current_task": current_task.model_dump(),
            "task_summary": task_summary,
            "recent_results": recent_results_summary,
        }

    def _build_task_summary(self, tasks: list[Task]) -> str:
        """Build a summary of all tasks and their status.

        Args:
            tasks: List of all tasks

        Returns:
            Formatted task summary
        """
        lines = ["Task Plan:"]
        for task in tasks:
            status_icon = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✓",
                "failed": "✗",
            }.get(task.status.value, "•")

            lines.append(f"  {status_icon} [{task.id}] {task.description}")

        return "\n".join(lines)

    def _build_results_summary(self) -> str:
        """Build a summary of recent results.

        Args:
            None

        Returns:
            Formatted results summary
        """
        if not self._recent_results:
            return "No recent results"

        lines = ["Recent Results:"]
        for result in self._recent_results:
            status = "✓" if result.success else "✗"
            lines.append(f"  {status} [{result.task_id}] {result.summary}")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all context."""
        self._recent_results.clear()
