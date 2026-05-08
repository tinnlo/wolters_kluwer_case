"""Main agent controller that orchestrates the research process."""

import uuid
from datetime import UTC, datetime

from .cli import CLI
from .context import ContextManager
from .executor import Executor
from .models import AgentSession, LogEntry, TaskStatus
from .planner import Planner
from .state import StateManager
from .synthesizer import Synthesizer
from .tools import ToolRegistry, WebSearchTool


class Agent:
    """Main agent controller for research tasks."""

    def __init__(
        self,
        state: StateManager,
        planner: Planner,
        executor: Executor,
        synthesizer: Synthesizer,
        context_manager: ContextManager,
        cli: CLI,
    ):
        """Initialize agent.

        Args:
            state: State manager
            planner: Planning component
            executor: Task executor
            synthesizer: Result synthesizer
            context_manager: Context manager
            cli: CLI interface
        """
        self.state = state
        self.planner = planner
        self.executor = executor
        self.synthesizer = synthesizer
        self.context = context_manager
        self.cli = cli

    async def run(self, goal: str) -> str:
        """Run the complete agent loop.

        Args:
            goal: The research goal

        Returns:
            Final synthesized report

        Raises:
            Exception: If agent execution fails
        """
        # Create session
        session_id = str(uuid.uuid4())
        session = AgentSession(
            session_id=session_id,
            goal=goal,
            status="planning",
        )
        self.state.create_session(session)
        self._log(session_id, "INFO", "Agent", f"Started session: {session_id}")

        try:
            # Phase 1: Planning
            self.cli.show_info("Phase 1: Planning")
            plan = await self.planner.create_plan(goal)

            # Save plan
            self.state.update_session(session_id, plan=plan, status="planning")

            # Save tasks
            for task in plan.tasks:
                self.state.save_task(session_id, task)

            self._log(
                session_id, "INFO", "Planner", f"Created plan with {len(plan.tasks)} tasks"
            )

            # Display plan and get confirmation
            if not self.cli.display_plan(plan):
                self.cli.show_warning("Plan rejected by user")
                self.state.update_session(session_id, status="cancelled")
                return "Research cancelled by user"

            # Phase 2: Execution
            self.cli.show_info("\nPhase 2: Execution")
            self.state.update_session(session_id, status="executing")

            while self.state.has_pending_tasks(session_id):
                # Get next task
                task = self.state.get_next_task(session_id)

                if not task:
                    # No more tasks available (all blocked or completed)
                    # Check if there are blocked tasks
                    all_tasks = self.state.get_session_tasks(session_id)
                    pending_tasks = [t for t in all_tasks if t.status == TaskStatus.PENDING]

                    if pending_tasks:
                        # Tasks are blocked by failed dependencies
                        self.cli.show_warning(
                            f"{len(pending_tasks)} task(s) blocked by failed dependencies"
                        )
                        for blocked_task in pending_tasks:
                            self.state.update_task_status(
                                session_id,
                                blocked_task.id,
                                TaskStatus.FAILED,
                                error="Blocked by failed dependencies",
                            )
                            self._log(
                                session_id,
                                "WARNING",
                                "Executor",
                                f"Task {blocked_task.id} blocked by failed dependencies",
                            )
                    break

                # Show progress
                self.cli.show_task_progress(task, "starting")

                # Build context
                all_tasks = self.state.get_session_tasks(session_id)
                context = self.context.get_context_for_task(goal, task, all_tasks)

                # Execute task
                self.cli.show_task_progress(task, "executing")
                result = await self.executor.execute_task(session_id, task, context)

                # Track result in context
                self.context.add_result(result)

                # Show result
                self.cli.show_tool_result(result.tool_name, result.summary, result.success)

                if result.success:
                    self.cli.show_task_progress(task, "completed")
                    self._log(
                        session_id,
                        "INFO",
                        "Executor",
                        f"Completed task {task.id}: {result.summary}",
                    )
                else:
                    self.cli.show_task_progress(task, "failed")
                    self._log(
                        session_id,
                        "WARNING",
                        "Executor",
                        f"Failed task {task.id}: {result.summary}",
                    )

            # Phase 3: Synthesis
            self.cli.show_info("\nPhase 3: Synthesis")
            self.state.update_session(session_id, status="synthesizing")

            # Get all results
            all_results = self.state.get_tool_results(session_id)

            # Filter successful results
            successful_results = [r for r in all_results if r.success]

            if not successful_results:
                error_msg = "No successful results to synthesize"
                self.cli.show_error(error_msg)
                self.state.update_session(session_id, status="failed")
                return error_msg

            # Synthesize final report
            final_report = await self.synthesizer.synthesize(goal, successful_results)

            # Save final report
            self.state.update_session(
                session_id,
                final_report=final_report,
                status="completed",
                completed_at=datetime.now(UTC),
            )

            self._log(session_id, "INFO", "Synthesizer", "Generated final report")

            # Display report
            self.cli.display_final_report(final_report)

            # Show summary
            all_tasks = self.state.get_session_tasks(session_id)
            session = self.state.get_session(session_id)
            if session:
                self.cli.show_session_summary(session, all_tasks)

            return final_report

        except Exception as e:
            self._log(session_id, "ERROR", "Agent", f"Agent failed: {str(e)}")
            self.state.update_session(session_id, status="failed")
            self.cli.show_error(f"Agent execution failed: {str(e)}")
            raise

    def _log(self, session_id: str, level: str, component: str, message: str) -> None:
        """Add a log entry.

        Args:
            session_id: Session ID
            level: Log level
            component: Component name
            message: Log message
        """
        log_entry = LogEntry(
            session_id=session_id,
            level=level,
            component=component,
            message=message,
        )
        self.state.add_log(log_entry)


def create_agent(db_path: str = "data/sessions.db") -> Agent:
    """Factory function to create a configured agent.

    Args:
        db_path: Path to SQLite database

    Returns:
        Configured Agent instance
    """
    # Initialize components
    state = StateManager(db_path)
    planner = Planner()
    synthesizer = Synthesizer()
    context_manager = ContextManager()
    cli = CLI()

    # Setup tool registry
    registry = ToolRegistry()
    registry.register(WebSearchTool())

    # Create executor
    executor = Executor(registry, state)

    # Create agent
    return Agent(state, planner, executor, synthesizer, context_manager, cli)
