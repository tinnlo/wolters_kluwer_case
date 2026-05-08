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
    table.add_column("Created", style="dim", width=20)

    for s in sessions:
        table.add_row(
            s.session_id,
            s.status.value,
            s.goal[:58] + "…" if len(s.goal) > 58 else s.goal,
            s.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


async def main() -> None:
    """Main CLI entry point."""
    load_dotenv()

    args = sys.argv[1:]

    # --list-sessions
    if args and args[0] == "--list-sessions":
        _cmd_list_sessions()
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
        try:
            await agent.resume(session_id)
        except ValueError as e:
            cli.show_error(str(e))
            sys.exit(1)
        except KeyboardInterrupt:
            cli.show_warning("\nResearch interrupted by user")
            sys.exit(1)
        except Exception as e:
            cli.show_error(f"Fatal error: {str(e)}")
            sys.exit(1)
        return

    # Normal run
    cli = CLI()
    cli.print_banner()

    if args:
        goal = " ".join(args)
    else:
        goal = cli.get_research_goal()

    cli.show_info("Initializing research agent...")
    agent = create_agent()

    try:
        await agent.run(goal)
    except KeyboardInterrupt:
        cli.show_warning("\nResearch interrupted by user")
        sys.exit(1)
    except Exception as e:
        cli.show_error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
