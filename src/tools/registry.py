"""Tool registry for managing and selecting tools."""

from typing import Optional

from ..models import Task
from .base import Tool


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        """Initialize empty tool registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool.

        Args:
            tool: The tool to register
        """
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name.

        Args:
            name: The tool name

        Returns:
            The tool if found, None otherwise
        """
        return self._tools.get(name)

    def select_tool(self, task: Task) -> Optional[Tool]:
        """Select the best tool for a task.

        Args:
            task: The task to find a tool for

        Returns:
            The best matching tool, or None if no tool can handle it
        """
        # If task specifies a tool, use that
        if task.tool_name:
            return self.get_tool(task.tool_name)

        # Otherwise, find first tool that can handle it
        for tool in self._tools.values():
            if tool.can_handle(task):
                return tool

        return None

    def list_tools(self) -> list[Tool]:
        """Get list of all registered tools.

        Returns:
            List of all tools
        """
        return list(self._tools.values())
