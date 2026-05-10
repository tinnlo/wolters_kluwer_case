#!/usr/bin/env python3
"""Main entry point for the research agent CLI."""

import asyncio
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.agent import create_agent
from src.cli import CLI

console = Console()

# Global reference to track current session for interrupt handling
_current_agent = None
_current_state = None


def _cmd_list_sessions(db_path: str = "data/sessions.db") -> None:
    """Print all past sessions in a table."""
    from src.state import StateManager

    state = StateManager(db_path)
    sessions = state.list_sessions()

    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Session ID", style="cyan", width=38)
    table.add_column("Status", style="white", width=14)
    table.add_column("Goal", style="white", width=60)
    table.add_column("Created (Local)", style="dim", width=20)

    for s in sessions:
        # Convert UTC to local time for display
        local_time = s.created_at.astimezone()
        table.add_row(
            s.session_id,
            s.status.value,
            s.goal[:58] + "…" if len(s.goal) > 58 else s.goal,
            local_time.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


def _cmd_view_session(session_id: str, db_path: str = "data/sessions.db") -> None:
    """Display a completed session's report and summary."""
    from src.state import StateManager

    state = StateManager(db_path)
    session = state.get_session(session_id)

    if not session:
        console.print(f"[red]Error: Session not found: {session_id}[/red]")
        sys.exit(1)

    cli = CLI()
    cli.print_banner()

    # Display session info
    cli.show_info(f"Session: {session_id}")
    cli.show_info(f"Goal: {session.goal}")
    cli.show_info(f"Status: {session.status.value}")
    console.print()

    # Display final report if available
    if session.final_report:
        cli.display_final_report(session.final_report)
    else:
        cli.show_warning("No final report available for this session.")
        console.print()

    # Display session summary
    tasks = state.get_session_tasks(session_id)
    cli.show_session_summary(session, tasks)


def _cmd_show_help() -> None:
    """Display help message."""
    help_text = """
[bold cyan]AI Research Assistant - Usage[/bold cyan]

[bold]Commands:[/bold]
  [cyan]python main.py[/cyan]                           Start a new research session (interactive)
  [cyan]python main.py "your research goal"[/cyan]      Start a new research session with a goal
  [cyan]python main.py --auto-approve "goal"[/cyan]     Start session with automatic plan approval
  [cyan]python main.py --list-sessions[/cyan]           List all past research sessions
  [cyan]python main.py --view <session-id>[/cyan]       View a completed session's report
  [cyan]python main.py --resume <session-id>[/cyan]     Resume an interrupted session
  [cyan]python main.py --help[/cyan]                    Show this help message

[bold]Examples:[/bold]
  [dim]# Start a new research session[/dim]
  python main.py "Compare React and Vue.js frameworks"

  [dim]# Start with automatic plan approval (non-interactive)[/dim]
  python main.py --auto-approve "Research WebAssembly adoption"

  [dim]# List all sessions[/dim]
  python main.py --list-sessions

  [dim]# View a completed session[/dim]
  python main.py --view 7ef84fb7-ba9f-474b-a938-7b4631fe9680

  [dim]# Resume an interrupted session[/dim]
  python main.py --resume 7ef84fb7-ba9f-474b-a938-7b4631fe9680
"""
    console.print(help_text)


async def main() -> None:
    """Main CLI entry point."""
    global _current_agent, _current_state

    load_dotenv()

    args = sys.argv[1:]

    # --help
    if args and args[0] in ["--help", "-h", "help"]:
        _cmd_show_help()
        return

    # --list-sessions
    if args and args[0] == "--list-sessions":
        _cmd_list_sessions()
        return

    # --view <session-id>
    if args and args[0] == "--view":
        if len(args) < 2:
            console.print("[red]Usage: research-agent --view <session-id>[/red]")
            sys.exit(1)
        session_id = args[1]
        _cmd_view_session(session_id)
        return

    # --resume <session-id>
    if args and args[0] == "--resume":
        if len(args) < 2:
            console.print("[red]Usage: research-agent --resume <session-id>[/red]")
            sys.exit(1)
        session_id = args[1]
        cli = CLI()
        cli.print_banner()
        cli.show_info(f"Resuming session: {session_id}")
        agent = create_agent()
        global _current_agent, _current_state
        _current_agent = agent
        _current_state = agent.state
        try:
            await agent.resume(session_id)
        except ValueError as e:
            cli.show_error(str(e))
            sys.exit(1)
        except KeyboardInterrupt:
            # Update session status to INTERRUPTED if we have a session
            if agent.current_session_id:
                from src.models import SessionStatus
                agent.state.update_session(agent.current_session_id, status=SessionStatus.INTERRUPTED)
            cli.show_warning("\nResearch interrupted by user")
            sys.exit(1)
        except Exception as e:
            cli.show_error(f"Fatal error: {str(e)}")
            sys.exit(1)
        return

    # Check for --auto-approve flag before rejecting unknown flags
    auto_approve = False
    if "--auto-approve" in args:
        auto_approve = True
        args.remove("--auto-approve")

    # Reject unknown flags (anything starting with -- that isn't handled above)
    unknown_flags = [a for a in args if a.startswith("--")]
    if unknown_flags:
        console.print(f"[red]Unknown option(s): {' '.join(unknown_flags)}[/red]")
        _cmd_show_help()
        sys.exit(1)

    # Normal run
    cli = CLI()
    cli.print_banner()

    if args:
        goal = " ".join(args)
    else:
        goal = cli.get_research_goal()

    cli.show_info("Initializing research agent...")
    agent = create_agent()
    _current_agent = agent
    _current_state = agent.state

    try:
        await agent.run(goal, auto_approve=auto_approve)
    except KeyboardInterrupt:
        # Update session status to INTERRUPTED if we have a session
        if agent.current_session_id:
            from src.models import SessionStatus
            agent.state.update_session(agent.current_session_id, status=SessionStatus.INTERRUPTED)
        cli.show_warning("\n\nResearch interrupted by user")
        cli.show_info("To resume this session later, use:")
        cli.show_info("  python main.py --list-sessions")
        cli.show_info("  python main.py --resume <session-id>")
        sys.exit(1)
    except Exception as e:
        cli.show_error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Update session status to INTERRUPTED if we have an active session
        if _current_agent and _current_agent.current_session_id and _current_state:
            from src.models import SessionStatus
            _current_state.update_session(
                _current_agent.current_session_id,
                status=SessionStatus.INTERRUPTED
            )
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)  # Standard exit code for SIGINT
