"""Web search tool using Tavily API."""

import os
from typing import Any

import httpx

from ..models import Task, ToolResult
from .base import Tool


class WebSearchTool(Tool):
    """Web search tool using Tavily API for AI-optimized search."""

    def __init__(self, api_key: str | None = None):
        """Initialize web search tool.

        Args:
            api_key: Tavily API key (defaults to TAVILY_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY not found in environment")

        self.api_url = "https://api.tavily.com/search"

    @property
    def name(self) -> str:
        """Return tool name."""
        return "web_search"

    @property
    def description(self) -> str:
        """Return tool description."""
        return "Search the web for information using AI-optimized search"

    def can_handle(self, task: Task) -> bool:
        """Check if this tool can handle the task.

        Args:
            task: The task to check

        Returns:
            True if task involves searching or finding information
        """
        keywords = [
            "search", "find", "look up", "research", "investigate", "explore",
            "compare", "identify", "analyze", "review", "survey", "examine",
            "discover", "learn about", "understand", "study", "gather information"
        ]
        description_lower = task.description.lower()

        return any(keyword in description_lower for keyword in keywords)

    async def execute(self, task: Task, context: dict) -> ToolResult:
        """Execute web search for the task.

        Args:
            task: The task to execute
            context: Additional context

        Returns:
            ToolResult with search results
        """
        try:
            # Extract search query from task description
            query = self._extract_query(task.description)

            # Call Tavily API
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.api_url,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "search_depth": "advanced",
                        "include_answer": True,
                        "include_raw_content": False,
                        "max_results": 5,
                    },
                )

                response.raise_for_status()
                data = response.json()

            # Process results
            results = data.get("results", [])
            answer = data.get("answer", "")

            # Format results
            summary = self._format_summary(query, results, answer)
            full_content = self._format_full_content(query, results, answer)

            # Extract metadata
            metadata = {
                "query": query,
                "num_results": len(results),
                "sources": [r.get("url") for r in results],
                "has_answer": bool(answer),
            }

            return ToolResult(
                tool_name=self.name,
                task_id=task.id,
                success=True,
                summary=summary,
                full_content=full_content,
                metadata=metadata,
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error: {e.response.status_code}"
            return ToolResult(
                tool_name=self.name,
                task_id=task.id,
                success=False,
                summary=f"Search failed: {error_msg}",
                full_content=str(e),
                metadata={"error": error_msg},
            )

        except Exception as e:
            error_msg = f"Search error: {str(e)}"
            return ToolResult(
                tool_name=self.name,
                task_id=task.id,
                success=False,
                summary=error_msg,
                full_content=str(e),
                metadata={"error": str(e)},
            )

    def _extract_query(self, description: str) -> str:
        """Extract search query from task description.

        Args:
            description: Task description

        Returns:
            Search query string
        """
        # Remove common action words
        query = description.lower()
        for prefix in ["search for", "find", "look up", "research", "investigate"]:
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
                break

        return query.strip()

    def _format_summary(
        self, query: str, results: list[dict[str, Any]], answer: str
    ) -> str:
        """Format a brief summary of search results.

        Args:
            query: The search query
            results: List of search results
            answer: AI-generated answer

        Returns:
            Brief summary string
        """
        if not results:
            return f"No results found for: {query}"

        summary_parts = [f"Found {len(results)} results for: {query}"]

        if answer:
            # Truncate answer if too long
            answer_preview = answer[:150] + "..." if len(answer) > 150 else answer
            summary_parts.append(f"Answer: {answer_preview}")

        return " | ".join(summary_parts)

    def _format_full_content(
        self, query: str, results: list[dict[str, Any]], answer: str
    ) -> str:
        """Format full search results content.

        Args:
            query: The search query
            results: List of search results
            answer: AI-generated answer

        Returns:
            Formatted full content
        """
        lines = [f"# Search Results for: {query}\n"]

        if answer:
            lines.append(f"## AI Answer\n{answer}\n")

        if results:
            lines.append("## Sources\n")
            for i, result in enumerate(results, 1):
                title = result.get("title", "Untitled")
                url = result.get("url", "")
                content = result.get("content", "")

                lines.append(f"### {i}. {title}")
                lines.append(f"URL: {url}")
                lines.append(f"{content}\n")

        return "\n".join(lines)
