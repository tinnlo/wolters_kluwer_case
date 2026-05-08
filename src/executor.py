"""Task executor that dispatches tasks to appropriate tools."""

from .models import Task, TaskStatus, ToolResult
from .state import StateManager
from .tools import ToolRegistry


class Executor:
    """Executes tasks using the appropriate tools."""

    def __init__(self, registry: ToolRegistry, state: StateManager):
        """Initialize executor.

        Args:
            registry: Tool registry for selecting tools
            state: State manager for persistence
        """
        self.registry = registry
        self.state = state

    async def execute_task(
        self, session_id: str, task: Task, context: dict
    ) -> ToolResult:
        """Execute a single task.

        Args:
            session_id: The session ID
            task: The task to execute
            context: Execution context

        Returns:
            ToolResult from execution

        Raises:
            ValueError: If no tool can handle the task
        """
        # Select appropriate tool
        tool = self.registry.select_tool(task)

        if not tool:
            # No tool available
            error_msg = f"No tool available to handle task: {task.description}"
            result = ToolResult(
                tool_name="none",
                task_id=task.id,
                success=False,
                summary=error_msg,
                full_content=error_msg,
                metadata={"error": "no_tool_available"},
            )

            # Update task as failed
            self.state.update_task_status(
                session_id, task.id, TaskStatus.FAILED, error=error_msg
            )

            return result

        # Update task status to in_progress
        self.state.update_task_status(session_id, task.id, TaskStatus.IN_PROGRESS)

        # Execute tool
        result = await tool.execute(task, context)

        # Save result
        self.state.save_tool_result(session_id, result)

        # Update task status based on result
        if result.success:
            self.state.update_task_status(
                session_id, task.id, TaskStatus.COMPLETED, result=result.summary
            )
        else:
            self.state.update_task_status(
                session_id, task.id, TaskStatus.FAILED, error=result.summary
            )

        return result
