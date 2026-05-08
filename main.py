#!/usr/bin/env python3
"""Main entry point for the research agent CLI."""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.agent import create_agent
from src.cli import CLI


async def main() -> None:
    """Main CLI entry point."""
    # Load environment variables
    load_dotenv()

    # Create CLI
    cli = CLI()

    # Print banner
    cli.print_banner()

    # Get research goal
    if len(sys.argv) > 1:
        # Goal provided as command line argument
        goal = " ".join(sys.argv[1:])
    else:
        # Prompt user for goal
        goal = cli.get_research_goal()

    # Create agent
    cli.show_info("Initializing research agent...")
    agent = create_agent()

    # Run agent
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
