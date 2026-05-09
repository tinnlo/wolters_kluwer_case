"""Main agent controller that orchestrates the research process."""

import uuid
from datetime import UTC, datetime
from typing import Literal

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
            # Phase 1: Planning (with refinement loop)
            self.cli.show_info("Phase 1: Planning")
            plan = None
            feedback = None
            max_refinements = 3
            refinement_count = 0
            approved = False

            # Generate initial plan
            plan = await self.planner.create_plan(goal, feedback)

            # Save plan
            self.state.update_session(session_id, plan=plan, status=SessionStatus.PLANNING)

            # Save tasks
            for t in plan.tasks:
                self.state.save_task(session_id, t)

            self._log(
                session_id, "INFO", "Planner", f"Created plan with {len(plan.tasks)} tasks"
            )

            # Display plan and get confirmation
            approved, user_feedback = self.cli.display_plan(plan, auto_approve=auto_approve)

            if not approved and user_feedback:
                feedback = user_feedback
                self._log(
                    session_id, "INFO", "Planner", f"User requested plan revision: {feedback}"
                )
            elif not approved:
                # User rejected without feedback
                self.cli.show_warning("Plan rejected by user without feedback")
                self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                return "Research cancelled by user"

            # Refinement loop
            while not approved and refinement_count < max_refinements:
                refinement_count += 1
                self.cli.show_info(f"Refining plan based on your feedback (attempt {refinement_count}/{max_refinements})...")

                plan = await self.planner.create_plan(goal, feedback)

                # Save plan
                self.state.update_session(session_id, plan=plan, status=SessionStatus.PLANNING)

                # Replace all tasks (deletes stale tasks from rejected plans)
                self.state.replace_session_tasks(session_id, plan.tasks)

                self._log(
                    session_id, "INFO", "Planner", f"Refined plan with {len(plan.tasks)} tasks"
                )

                # Display plan and get confirmation
                approved, user_feedback = self.cli.display_plan(plan, auto_approve=auto_approve)

                if approved:
                    break

                if user_feedback:
                    feedback = user_feedback
                    self._log(
                        session_id, "INFO", "Planner", f"User requested plan revision: {feedback}"
                    )
                else:
                    # User rejected without feedback
                    self.cli.show_warning("Plan rejected by user without feedback")
                    self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                    return "Research cancelled by user"

            if refinement_count >= max_refinements and not approved:
                self.cli.show_warning(f"Maximum plan refinement attempts ({max_refinements}) reached")
                self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                return "Research cancelled: could not agree on a plan"

            if not plan:
                raise ValueError("No plan was generated")

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

                # Task is guaranteed to be non-None here (mypy type narrowing)
                assert task is not None

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
            final_session = self.state.get_session(session_id)
            if final_session:
                self.cli.show_session_summary(final_session, all_tasks)
            else:
                self.cli.show_warning("Session not found for summary display")

            return final_report

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
        - EXECUTING/SYNTHESIZING: Re-execute pending/failed tasks
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

        self._log(session_id, "INFO", "Agent", f"Resuming session: {session_id}")
        self.cli.show_info(f"Resuming session {session_id} (goal: {session.goal})")

        goal = session.goal

        try:
            # If session was interrupted during planning, continue plan refinement
            if session.status == SessionStatus.PLANNING:
                self.cli.show_info("\nResuming Phase 1: Planning")

                # Get existing plan if any
                plan = session.plan
                feedback = None
                max_refinements = 3
                refinement_count = 0
                approved = False

                # If there's already a plan, show it for approval
                if plan:
                    self.cli.show_info("Showing previously generated plan...")
                    approved, user_feedback = self.cli.display_plan(plan)

                    if approved:
                        # User approved the existing plan, proceed to execution
                        pass
                    elif user_feedback:
                        # User wants to refine the plan
                        feedback = user_feedback
                    else:
                        # User rejected without feedback
                        self.cli.show_warning("Plan rejected by user without feedback")
                        self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                        return "Research cancelled by user"
                else:
                    # No plan exists yet, generate one
                    self.cli.show_info("No plan found. Generating initial plan...")
                    plan = await self.planner.create_plan(goal)
                    self.state.update_session(session_id, plan=plan, status=SessionStatus.PLANNING)

                    # Save tasks
                    for t in plan.tasks:
                        self.state.save_task(session_id, t)

                    self._log(session_id, "INFO", "Planner", f"Created plan with {len(plan.tasks)} tasks")

                    # Show plan for approval
                    approved, user_feedback = self.cli.display_plan(plan)

                    if not approved and user_feedback:
                        feedback = user_feedback
                    elif not approved:
                        self.cli.show_warning("Plan rejected by user without feedback")
                        self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                        return "Research cancelled by user"

                # Continue refinement loop if needed
                while not approved and refinement_count < max_refinements:
                    refinement_count += 1
                    self.cli.show_info(f"Refining plan based on your feedback (attempt {refinement_count}/{max_refinements})...")

                    plan = await self.planner.create_plan(goal, feedback)
                    self.state.update_session(session_id, plan=plan, status=SessionStatus.PLANNING)

                    # Replace all tasks to prevent stale task execution
                    self.state.replace_session_tasks(session_id, plan.tasks)

                    self._log(session_id, "INFO", "Planner", f"Refined plan with {len(plan.tasks)} tasks")

                    approved, user_feedback = self.cli.display_plan(plan)

                    if approved:
                        break

                    if user_feedback:
                        feedback = user_feedback
                        self._log(session_id, "INFO", "Planner", f"User requested plan revision: {feedback}")
                    else:
                        self.cli.show_warning("Plan rejected by user without feedback")
                        self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                        return "Research cancelled by user"

                if refinement_count >= max_refinements and not approved:
                    self.cli.show_warning(f"Maximum plan refinement attempts ({max_refinements}) reached")
                    self.state.update_session(session_id, status=SessionStatus.CANCELLED)
                    return "Research cancelled: could not agree on a plan"

                if not plan:
                    raise ValueError("No plan was generated")

            # If session was interrupted during execution or synthesis, reset failed/in-progress tasks
            else:
                # Reset IN_PROGRESS and FAILED tasks to PENDING so they are retried.
                all_tasks = self.state.get_session_tasks(session_id)
                for existing_task in all_tasks:
                    if existing_task.status in (TaskStatus.IN_PROGRESS, TaskStatus.FAILED):
                        self.state.delete_tool_results_for_task(session_id, existing_task.id)
                        self.state.update_task_status(session_id, existing_task.id, TaskStatus.PENDING)
                        self._log(
                            session_id,
                            "WARNING",
                            "Agent",
                            f"Resetting {existing_task.status.value} task {existing_task.id} to PENDING for retry",
                        )

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

                # Task is guaranteed to be non-None here (mypy type narrowing)
                assert task is not None

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
