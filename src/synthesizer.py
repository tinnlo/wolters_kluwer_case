"""Synthesizer that creates final reports from research results."""

import os

from openai import OpenAI

from .models import ToolResult


class Synthesizer:
    """Synthesizes research results into coherent final reports."""

    def __init__(self, api_key: str | None = None):
        """Initialize synthesizer.

        Args:
            api_key: OpenAI API key
        """
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4o"  # Using gpt-4o as gpt-5.4 is not available yet

        # Load synthesis prompt
        prompt_path = os.path.join(
            os.path.dirname(__file__), "prompts", "synthesizer.txt"
        )
        with open(prompt_path, "r") as f:
            self.system_prompt = f.read()

    async def synthesize(self, goal: str, results: list[ToolResult]) -> str:
        """Synthesize research results into a final report.

        Args:
            goal: The original research goal
            results: All tool results from the session

        Returns:
            Final synthesized report as markdown

        Raises:
            ValueError: If synthesis fails
        """
        try:
            # Build context from results
            context = self._build_context(goal, results)

            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": context},
                ],
                temperature=0.7,
                max_tokens=2000,
            )

            # Extract report
            report = response.choices[0].message.content

            if not report:
                raise ValueError("Empty response from OpenAI")

            return report

        except Exception as e:
            raise ValueError(f"Failed to synthesize report: {e}")

    def _build_context(self, goal: str, results: list[ToolResult]) -> str:
        """Build context for synthesis.

        Args:
            goal: The research goal
            results: All tool results

        Returns:
            Formatted context string
        """
        lines = [
            f"# Research Goal\n{goal}\n",
            f"# Research Results\n",
            f"Total tasks completed: {len(results)}\n",
        ]

        # Add each result
        for i, result in enumerate(results, 1):
            lines.append(f"## Result {i}: Task {result.task_id}")
            lines.append(f"Tool: {result.tool_name}")
            lines.append(f"Status: {'Success' if result.success else 'Failed'}")
            lines.append(f"\n{result.full_content}\n")

        lines.append("\n# Instructions")
        lines.append(
            "Synthesize the above research results into a comprehensive, "
            "well-structured report that addresses the research goal."
        )

        return "\n".join(lines)
