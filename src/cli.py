"""Command-line interface for the research agent."""

import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.markdown import Markdown

from .models import AgentSession, LogEntry, ResearchPlan, Task, TaskStatus


class CLI:
    """Rich-based command-line interface."""

    def __init__(self) -> None:
        """Initialize CLI with Rich console."""
        self.console = Console()

    def print_banner(self) -> None:
        """Print welcome banner."""
        banner = """
        [bold cyan]╔═══════════════════════════════════════════════════════╗[/bold cyan]
        [bold cyan]║[/bold cyan]  [bold white]AI Research Assistant[/bold white]                            [bold cyan]║[/bold cyan]
        [bold cyan]║[/bold cyan]  Break down complex research goals into actions   [bold cyan]║[/bold cyan]
        [bold cyan]╚═══════════════════════════════════════════════════════╝[/bold cyan]
        """
        self.console.print(banner)

    def get_research_goal(self) -> str:
        """Prompt user for research goal."""
        self.console.print("\n[bold yellow]What would you like to research?[/bold yellow]")
        self.console.print("[dim]Example: 'Research the current state of WebAssembly adoption'[/dim]\n")

        goal = self.console.input("[bold cyan]Goal:[/bold cyan] ").strip()

        if not goal:
            self.console.print("[red]Error: Goal cannot be empty[/red]")
            sys.exit(1)

        return goal

    def display_plan(self, plan: ResearchPlan) -> bool:
        """Display the research plan and get user confirmation."""
        self.console.print("\n[bold green]✓ Research Plan Generated[/bold green]\n")

        # Create table for tasks
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("ID", style="cyan", width=8)
        table.add_column("Task", style="white", width=60)
        table.add_column("Dependencies", style="yellow", width=15)

        for task in plan.tasks:
            deps = ", ".join(task.dependencies) if task.dependencies else "None"
            table.add_row(task.id, task.description, deps)

        self.console.print(table)

        # Get confirmation
        self.console.print("\n[bold yellow]Proceed with this plan?[/bold yellow] [dim](yes/no)[/dim]")
        response = self.console.input("[bold cyan]>[/bold cyan] ").strip().lower()

        return response in ["yes", "y"]

    def show_task_progress(self, task: Task, status: str) -> None:
        """Show task execution progress."""
        status_icons = {
            "starting": "⏳",
            "executing": "🔄",
            "completed": "✓",
            "failed": "✗"
        }

        status_colors = {
            "starting": "yellow",
            "executing": "cyan",
            "completed": "green",
            "failed": "red"
        }

        icon = status_icons.get(status, "•")
        color = status_colors.get(status, "white")

        self.console.print(
            f"[{color}]{icon} [{task.id}] {task.description}[/{color}]"
        )

    def show_tool_result(self, tool_name: str, summary: str, success: bool) -> None:
        """Display tool execution result."""
        if success:
            self.console.print(f"  [dim]→ {tool_name}: {summary}[/dim]")
        else:
            self.console.print(f"  [red]→ {tool_name}: {summary}[/red]")

    def display_final_report(self, report: str) -> None:
        """Display the final synthesized report."""
        self.console.print("\n" + "="*80 + "\n")
        self.console.print("[bold green]📊 Final Research Report[/bold green]\n")

        # Render as markdown for better formatting
        md = Markdown(report)
        self.console.print(md)

        self.console.print("\n" + "="*80 + "\n")

    def show_error(self, message: str) -> None:
        """Display error message."""
        self.console.print(f"\n[bold red]Error:[/bold red] {message}\n")

    def show_info(self, message: str) -> None:
        """Display info message."""
        self.console.print(f"[cyan]ℹ[/cyan] {message}")

    def show_warning(self, message: str) -> None:
        """Display warning message."""
        self.console.print(f"[yellow]⚠[/yellow] {message}")

    def show_session_summary(self, session: AgentSession, tasks: list[Task]) -> None:
        """Display session summary statistics."""
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        total = len(tasks)

        summary = f"""
[bold]Session Summary[/bold]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Session ID: {session.session_id}
Goal: {session.goal}
Status: {session.status}

Tasks: {completed}/{total} completed, {failed} failed
        """

        panel = Panel(summary.strip(), border_style="cyan")
        self.console.print(panel)

    def create_progress_context(self, description: str) -> Progress:
        """Create a progress context for long-running operations."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        )
