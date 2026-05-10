"""Main agent controller that orchestrates the research process."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from .cli import CLI
from .context import ContextManager
from .executor import Executor
from .models import AgentSession, LogEntry, ResearchPlan, SessionStatus, Task, TaskStatus, ToolResult
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
        self._max_plan_refinements = 3
        self.current_session_id: str | None = None

    async def run(self, goal: str, auto_approve: bool = False) -> str:
        """Run the complete agent loop.

        Args:
            goal: The research goal
            auto_approve: If True, automatically approve plans without user confirmation

        Returns:
            Final synthesized report

        Raises:
            Exception: If agent execution fails
        """
        # Create session
        session_id = str(uuid.uuid4())
        self.current_session_id = session_id
        session = AgentSession(
            session_id=session_id,
            goal=goal,
            status=SessionStatus.PLANNING,
        )
        self.state.create_session(session)
        self._log(session_id, "INFO", "Agent", f"Started session: {session_id}")

        # Display session ID to user
        self.cli.show_info(f"Session ID: {session_id}")
        self.cli.show_info("(Press Ctrl+C to pause, then resume with: python main.py --resume <session-id>)")
        self.cli.console.print()

        try:
            self.cli.show_info("Phase 1: Planning")
            plan, cancellation_message = await self._prepare_plan_for_run(
                session_id, goal, auto_approve=auto_approve
            )
            if cancellation_message:
                return cancellation_message
            self._ensure_plan_exists(plan)
            final_report = await self._execute_and_synthesize(
                session_id,
                goal,
                execution_banner="\nPhase 2: Execution",
                synthesis_banner="\nPhase 3: Synthesis",
                synthesis_log_message="Generated final report",
            )
            self._display_session_summary(session_id)
            return final_report

        except KeyboardInterrupt:
            self._log(session_id, "WARNING", "Agent", "Session interrupted by user")
            self.state.update_session(session_id, status=SessionStatus.INTERRUPTED)
            raise
        except Exception as e:
            self._log(session_id, "ERROR", "Agent", f"Agent failed: {str(e)}")
            self.state.update_session(session_id, status=SessionStatus.FAILED)
            self.cli.show_error(f"Agent execution failed: {str(e)}")
            raise

    def _log(
        self,
        session_id: str,
        level: Literal["INFO", "WARNING", "ERROR"],
        component: str,
        message: str,
    ) -> None:
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

        Sessions can be resumed from any phase:
        - PLANNING: Continue plan refinement and approval
        - EXECUTING/SYNTHESIZING: Continue from the last incomplete step, retrying any in-progress or failed tasks
        - FAILED: Retry from where it failed

        Args:
            session_id: ID of the session to resume

        Returns:
            Final synthesized report

        Raises:
            ValueError: If the session does not exist or is already completed/cancelled
        """
        session = self.state.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.status == SessionStatus.COMPLETED:
            raise ValueError(
                f"Session {session_id} is already completed. "
                "Use --view to display the stored report."
            )
        if session.status == SessionStatus.CANCELLED:
            raise ValueError(
                f"Session {session_id} was cancelled by the user. "
                "Start a new session instead."
            )

        self.current_session_id = session_id

        self._log(session_id, "INFO", "Agent", f"Resuming session: {session_id}")
        self.cli.show_info(f"Resuming session {session_id} (goal: {session.goal})")

        goal = session.goal

        try:
            if session.status == SessionStatus.PLANNING:
                self.cli.show_info("\nResuming Phase 1: Planning")
                plan, cancellation_message = await self._prepare_plan_for_resume(
                    session_id, goal, session.plan
                )
                if cancellation_message:
                    return cancellation_message
                self._ensure_plan_exists(plan)
            else:
                self._reset_retryable_tasks(session_id)

            final_report = await self._execute_and_synthesize(
                session_id,
                goal,
                execution_banner="\nResuming Phase 2: Execution",
                synthesis_banner="\nPhase 3: Synthesis",
                synthesis_log_message="Generated final report (resumed)",
            )
            self._display_session_summary(session_id)
            return final_report

        except KeyboardInterrupt:
            self._log(session_id, "WARNING", "Agent", "Session interrupted by user")
            self.state.update_session(session_id, status=SessionStatus.INTERRUPTED)
            raise
        except Exception as e:
            self._log(session_id, "ERROR", "Agent", f"Resume failed: {str(e)}")
            self.state.update_session(session_id, status=SessionStatus.FAILED)
            self.cli.show_error(f"Resume failed: {str(e)}")
            raise

    async def _prepare_plan_for_run(
        self, session_id: str, goal: str, auto_approve: bool
    ) -> tuple[ResearchPlan | None, str | None]:
        """Create, store, and refine the initial run plan until approval."""
        plan = await self._create_initial_plan(session_id, goal)
        return await self._approve_or_refine_plan(
            session_id, goal, plan, auto_approve=auto_approve
        )

    async def _prepare_plan_for_resume(
        self, session_id: str, goal: str, existing_plan: ResearchPlan | None
    ) -> tuple[ResearchPlan | None, str | None]:
        """Resume planning from an existing or freshly generated plan."""
        if existing_plan:
            self.cli.show_info("Showing previously generated plan...")
            plan = existing_plan
        else:
            self.cli.show_info("No plan found. Generating initial plan...")
            plan = await self._create_initial_plan(session_id, goal)
        return await self._approve_or_refine_plan(session_id, goal, plan)

    async def _create_initial_plan(self, session_id: str, goal: str) -> ResearchPlan:
        """Generate and store the first plan for a session."""
        plan = await self._generate_and_store_plan(session_id, goal)
        self._log(
            session_id, "INFO", "Planner", f"Created plan with {len(plan.tasks)} tasks"
        )
        return plan

    async def _generate_and_store_plan(
        self, session_id: str, goal: str, feedback: str | None = None
    ) -> ResearchPlan:
        """Generate a new plan and persist it for the session."""
        plan = await self.planner.create_plan(goal, feedback)
        self.state.update_session(session_id, plan=plan, status=SessionStatus.PLANNING)
        self.state.replace_session_tasks(session_id, plan.tasks)
        return plan

    async def _approve_or_refine_plan(
        self,
        session_id: str,
        goal: str,
        plan: ResearchPlan,
        auto_approve: bool = False,
    ) -> tuple[ResearchPlan | None, str | None]:
        """Drive the user approval loop for a plan."""
        approved, feedback = self._display_plan_for_approval(
            session_id, plan, auto_approve=auto_approve
        )
        if approved:
            return plan, None
        if feedback is None:
            return None, self._cancel_session(session_id)

        refinement_count = 0
        while refinement_count < self._max_plan_refinements:
            refinement_count += 1
            self.cli.show_info(
                f"Refining plan based on your feedback (attempt {refinement_count}/{self._max_plan_refinements})..."
            )
            plan = await self._generate_and_store_plan(session_id, goal, feedback)
            self._log(
                session_id, "INFO", "Planner", f"Refined plan with {len(plan.tasks)} tasks"
            )
            approved, feedback = self._display_plan_for_approval(
                session_id, plan, auto_approve=auto_approve
            )
            if approved:
                return plan, None
            if feedback is None:
                return None, self._cancel_session(session_id)

        self.cli.show_warning(
            f"Maximum plan refinement attempts ({self._max_plan_refinements}) reached"
        )
        self.state.update_session(session_id, status=SessionStatus.CANCELLED)
        return None, "Research cancelled: could not agree on a plan"

    def _display_plan_for_approval(
        self, session_id: str, plan: ResearchPlan, auto_approve: bool = False
    ) -> tuple[bool, str | None]:
        """Display plan to user and return approval status with optional feedback.

        Args:
            session_id: Current session ID for logging
            plan: The research plan to display
            auto_approve: If True, automatically approve without user prompt

        Returns:
            Tuple of (approved, feedback) where feedback is None if approved or rejected without feedback
        """
        approved, user_feedback = self.cli.display_plan(plan, auto_approve=auto_approve)
        if approved:
            return True, None
        if user_feedback:
            self._log(
                session_id, "INFO", "Planner", f"User requested plan revision: {user_feedback}"
            )
            return False, user_feedback
        self.cli.show_warning("Plan rejected by user without feedback")
        return False, None

    def _cancel_session(self, session_id: str) -> str:
        """Cancel the current session after a user rejection."""
        self.state.update_session(session_id, status=SessionStatus.CANCELLED)
        return "Research cancelled by user"

    def _ensure_plan_exists(self, plan: ResearchPlan | None) -> None:
        """Guard against missing plan after approval loop."""
        if not plan:
            raise ValueError("No plan was generated")

    def _reset_retryable_tasks(self, session_id: str) -> None:
        """Reset in-progress and failed tasks for a resumed retry."""
        for existing_task in self.state.get_session_tasks(session_id):
            if existing_task.status in (TaskStatus.IN_PROGRESS, TaskStatus.FAILED):
                self.state.delete_tool_results_for_task(session_id, existing_task.id)
                self.state.update_task_status(
                    session_id, existing_task.id, TaskStatus.PENDING
                )
                self._log(
                    session_id,
                    "WARNING",
                    "Agent",
                    f"Resetting {existing_task.status.value} task {existing_task.id} to PENDING for retry",
                )

    async def _execute_and_synthesize(
        self,
        session_id: str,
        goal: str,
        execution_banner: str,
        synthesis_banner: str,
        synthesis_log_message: str,
    ) -> str:
        """Run execution and synthesis phases for a session."""
        self.cli.show_info(execution_banner)
        self.state.update_session(session_id, status=SessionStatus.EXECUTING)
        await self._execute_pending_tasks(session_id, goal)

        self.cli.show_info(synthesis_banner)
        self.state.update_session(session_id, status=SessionStatus.SYNTHESIZING)

        successful_results = self._get_successful_results(session_id)
        if not successful_results:
            error_msg = "No successful results to synthesize"
            self.cli.show_error(error_msg)
            self.state.update_session(session_id, status=SessionStatus.FAILED)
            return error_msg

        final_report = await self.synthesizer.synthesize(goal, successful_results)
        self.state.update_session(
            session_id,
            final_report=final_report,
            status=SessionStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
        self._log(session_id, "INFO", "Synthesizer", synthesis_log_message)
        self.cli.display_final_report(final_report)
        return final_report

    async def _execute_pending_tasks(self, session_id: str, goal: str) -> None:
        """Execute pending tasks until nothing actionable remains."""
        while self.state.has_pending_tasks(session_id):
            task = self.state.get_next_task(session_id)
            if not task:
                self._fail_blocked_pending_tasks(session_id)
                break
            # Task is guaranteed to be non-None here (mypy type narrowing)
            assert task is not None
            await self._execute_task(session_id, goal, task)

    async def _execute_task(self, session_id: str, goal: str, task: Task) -> None:
        """Execute a single task with current session context."""
        self.cli.show_task_progress(task, "starting")
        context = self.context.get_context_for_task(
            goal, task, self.state.get_session_tasks(session_id)
        )
        self.cli.show_task_progress(task, "executing")
        result = await self.executor.execute_task(session_id, task, context)
        self.context.add_result(result)
        self.cli.show_tool_result(result.tool_name, result.summary, result.success)

        if result.success:
            self.cli.show_task_progress(task, "completed")
            self._log(
                session_id, "INFO", "Executor", f"Completed task {task.id}: {result.summary}"
            )
            return

        self.cli.show_task_progress(task, "failed")
        self._log(
            session_id, "WARNING", "Executor", f"Failed task {task.id}: {result.summary}"
        )

    def _fail_blocked_pending_tasks(self, session_id: str) -> None:
        """Mark pending tasks as failed when their dependencies cannot succeed."""
        pending_tasks = [
            task
            for task in self.state.get_session_tasks(session_id)
            if task.status == TaskStatus.PENDING
        ]
        if not pending_tasks:
            return

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

    def _get_successful_results(self, session_id: str) -> list[ToolResult]:
        """Return successful tool results for synthesis."""
        return [r for r in self.state.get_tool_results(session_id) if r.success]

    def _display_session_summary(self, session_id: str) -> None:
        """Display the final session summary if the session still exists."""
        session = self.state.get_session(session_id)
        if session:
            self.cli.show_session_summary(session, self.state.get_session_tasks(session_id))
        else:
            self.cli.show_warning("Session not found for summary display")


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
    cli = CLI()
    synthesizer = Synthesizer(cli=cli)
    context_manager = ContextManager()

    # Setup tool registry
    registry = ToolRegistry()
    registry.register(WebSearchTool())

    # Create executor
    executor = Executor(registry, state)

    # Create agent
    return Agent(state, planner, executor, synthesizer, context_manager, cli)
