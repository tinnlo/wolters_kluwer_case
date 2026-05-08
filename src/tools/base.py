"""Base tool interface."""

from abc import ABC, abstractmethod

from ..models import Task, ToolResult


class Tool(ABC):
    """Abstract base class for all tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the tool name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Return a description of what the tool does."""
        pass

    @abstractmethod
    async def execute(self, task: Task, context: dict) -> ToolResult:
        """Execute the tool for a given task.

        Args:
            task: The task to execute
            context: Additional context (session info, previous results, etc.)

        Returns:
            ToolResult with execution outcome
        """
        pass

    @abstractmethod
    def can_handle(self, task: Task) -> bool:
        """Check if this tool can handle the given task.

        Args:
            task: The task to check

        Returns:
            True if this tool can handle the task
        """
        pass
