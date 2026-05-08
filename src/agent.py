"""Main agent controller that orchestrates the research process."""

import uuid
from datetime import UTC, datetime

from .cli import CLI
from .context import ContextManager
from .executor import Executor
from .models import AgentSession, LogEntry, SessionStatus, TaskStatus
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
            status=SessionStatus.PLANNING,
        )
        self.state.create_session(session)
        self._log(session_id, "INFO", "Agent", f"Started session: {session_id}")

        try:
            # Phase 1: Planning
            self.cli.show_info("Phase 1: Planning")
            plan = await self.planner.create_plan(goal)

            # Save plan
            self.state.update_session(session_id, plan=plan, status=SessionStatus.PLANNING)

            # Save tasks
            for task in plan.tasks:
                self.state.save_task(session_id, task)

            self._log(
                session_id, "INFO", "Planner", f"Created plan with {len(plan.tasks)} tasks"
            )

            # Display plan and get confirmation
            if not self.cli.display_plan(plan):
                self.cli.show_warning("Plan rejected by user")
                self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                return "Research cancelled by user"

            # Phase 2: Execution
            self.cli.show_info("\nPhase 2: Execution")
            self.state.update_session(session_id, status=SessionStatus.EXECUTING)

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
            self.state.update_session(session_id, status=SessionStatus.SYNTHESIZING)

            # Get all results
            all_results = self.state.get_tool_results(session_id)

            # Filter successful results
            successful_results = [r for r in all_results if r.success]

            if not successful_results:
                error_msg = "No successful results to synthesize"
                self.cli.show_error(error_msg)
                self.state.update_session(session_id, status=SessionStatus.FAILED)
                return error_msg

            # Synthesize final report
            final_report = await self.synthesizer.synthesize(goal, successful_results)

            # Save final report
            self.state.update_session(
                session_id,
                final_report=final_report,
                status=SessionStatus.COMPLETED,
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
            self.state.update_session(session_id, status=SessionStatus.FAILED)
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


    async def resume(self, session_id: str) -> str:
        """Resume an interrupted session from where it left off.

        Only tasks that are still PENDING (or were IN_PROGRESS when the
        session was interrupted) will be re-executed.  Completed tasks and
        their stored results are reused as-is for the final synthesis.

        Args:
            session_id: ID of the session to resume

        Returns:
            Final synthesized report

        Raises:
            ValueError: If the session does not exist or is already completed
        """
        session = self.state.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.status == SessionStatus.COMPLETED:
            raise ValueError(
                f"Session {session_id} is already completed. "
                "Load the stored report instead of re-running."
            )
        if session.status in (SessionStatus.CANCELLED, SessionStatus.PLANNING):
            raise ValueError(
                f"Session {session_id} has status '{session.status.value}' and cannot be "
                "resumed. CANCELLED sessions were rejected by the user; PLANNING sessions "
                "never finished plan confirmation. Start a new session instead."
            )

        self._log(session_id, "INFO", "Agent", f"Resuming session: {session_id}")
        self.cli.show_info(f"Resuming session {session_id} (goal: {session.goal})")

        # Reset IN_PROGRESS and FAILED tasks to PENDING so they are retried.
        # IN_PROGRESS tasks were interrupted mid-execution (e.g. process killed).
        # FAILED tasks failed due to transient errors (network, API timeout) and
        # are safe to retry; their dependencies may now be completable.
        all_tasks = self.state.get_session_tasks(session_id)
        for task in all_tasks:
            if task.status in (TaskStatus.IN_PROGRESS, TaskStatus.FAILED):
                # Clear any partially-saved tool results before retrying.
                # An IN_PROGRESS task may have written a result to the DB
                # (via save_tool_result) before the process died or the
                # status was updated.  Keeping that stale result would cause
                # synthesis to see two results for the same task — the old
                # partial one plus the new retry — duplicating evidence and
                # inflating citations.
                self.state.delete_tool_results_for_task(session_id, task.id)
                self.state.update_task_status(session_id, task.id, TaskStatus.PENDING)
                self._log(
                    session_id,
                    "WARNING",
                    "Agent",
                    f"Resetting {task.status.value} task {task.id} to PENDING for retry",
                )

        goal = session.goal

        try:
            # Phase 2 (resumed): Execution
            self.cli.show_info("\nResuming Phase 2: Execution")
            self.state.update_session(session_id, status=SessionStatus.EXECUTING)

            while self.state.has_pending_tasks(session_id):
                task = self.state.get_next_task(session_id)

                if not task:
                    all_tasks = self.state.get_session_tasks(session_id)
                    pending_tasks = [t for t in all_tasks if t.status == TaskStatus.PENDING]
                    if pending_tasks:
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
                    break

                self.cli.show_task_progress(task, "starting")
                all_tasks = self.state.get_session_tasks(session_id)
                context = self.context.get_context_for_task(goal, task, all_tasks)

                self.cli.show_task_progress(task, "executing")
                result = await self.executor.execute_task(session_id, task, context)
                self.context.add_result(result)
                self.cli.show_tool_result(result.tool_name, result.summary, result.success)

                if result.success:
                    self.cli.show_task_progress(task, "completed")
                    self._log(session_id, "INFO", "Executor", f"Completed task {task.id}")
                else:
                    self.cli.show_task_progress(task, "failed")
                    self._log(session_id, "WARNING", "Executor", f"Failed task {task.id}")

            # Phase 3: Synthesis
            self.cli.show_info("\nPhase 3: Synthesis")
            self.state.update_session(session_id, status=SessionStatus.SYNTHESIZING)

            all_results = self.state.get_tool_results(session_id)
            successful_results = [r for r in all_results if r.success]

            if not successful_results:
                error_msg = "No successful results to synthesize"
                self.cli.show_error(error_msg)
                self.state.update_session(session_id, status=SessionStatus.FAILED)
                return error_msg

            final_report = await self.synthesizer.synthesize(goal, successful_results)

            from datetime import UTC, datetime as _dt
            self.state.update_session(
                session_id,
                final_report=final_report,
                status=SessionStatus.COMPLETED,
                completed_at=_dt.now(UTC),
            )

            self._log(session_id, "INFO", "Synthesizer", "Generated final report (resumed)")
            self.cli.display_final_report(final_report)

            all_tasks = self.state.get_session_tasks(session_id)
            resumed_session = self.state.get_session(session_id)
            if resumed_session:
                self.cli.show_session_summary(resumed_session, all_tasks)

            return final_report

        except Exception as e:
            self._log(session_id, "ERROR", "Agent", f"Resume failed: {str(e)}")
            self.state.update_session(session_id, status=SessionStatus.FAILED)
            self.cli.show_error(f"Resume failed: {str(e)}")
            raise


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
