"""Synthesizer that creates final reports from research results."""

import os

from openai import AsyncOpenAI

from .models import ToolResult


class Synthesizer:
    """Synthesizes research results into coherent final reports."""

    def __init__(self, api_key: str | None = None):
        """Initialize synthesizer.

        Args:
            api_key: OpenAI API key
        """
        self.client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.1")

        # Load synthesis prompt
        prompt_path = os.path.join(
            os.path.dirname(__file__), "prompts", "synthesizer.txt"
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
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
            context, source_count = self._build_context(goal, results)

            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": context},
                ],
                temperature=0.7,
                max_completion_tokens=8000,
            )

            # Extract report
            report = response.choices[0].message.content

            if not report:
                raise ValueError("Empty response from OpenAI")

            # Clamp citations to what the LLM actually listed in its ## Sources
            # section.  The LLM may receive N sources in the prompt but only cite
            # M < N in its Sources section; body citations referencing indices
            # M+1..N are then dangling.  Using source_count (the prompt count)
            # as the clamp bound lets those dangling references through.
            # Instead we count how many numbered entries the LLM wrote in its own
            # Sources section and clamp to that — guaranteeing body citations and
            # the Sources list are always consistent.
            emitted_count = self._count_emitted_sources(report)
            clamp = emitted_count if emitted_count > 0 else source_count
            # Always strip out-of-range citations.  When clamp=0 (no sources),
            # _remove_out_of_range_citations removes every [n] reference,
            # which is the correct behaviour for a zero-source synthesis.
            report = self._remove_out_of_range_citations(report, clamp)

            return report

        except Exception as e:
            raise ValueError(f"Failed to synthesize report: {e}")

    def _build_context(self, goal: str, results: list[ToolResult]) -> tuple[str, int]:
        """Build context for synthesis, including source URLs for citation.

        The per-result ``full_content`` may contain its own ``## Sources``
        section (written by the tool).  That embedded section uses a local
        1-based numbering that conflicts with the global ``# Available Sources``
        list built here.  We strip it so the LLM only sees one numbering
        scheme and cannot produce out-of-range citation numbers.

        Args:
            goal: The research goal
            results: All tool results

        Returns:
            Tuple of (formatted context string, number of unique sources).
            The source count is returned so ``synthesize`` can post-process
            the report to remove any out-of-range citations.
        """
        lines = [
            f"# Research Goal\n{goal}\n",
            "# Research Results\n",
            f"Total tasks completed: {len(results)}\n",
        ]

        # Collect all sources for a deduplicated reference list
        all_sources: list[dict] = []
        seen_urls: set[str] = set()

        # Add each result
        for i, result in enumerate(results, 1):
            lines.append(f"## Result {i}: Task {result.task_id}")
            lines.append(f"Tool: {result.tool_name}")
            lines.append(f"Status: {'Success' if result.success else 'Failed'}")

            # Strip embedded Sources block, then strip any pre-existing [n]
            # citation markers from Tavily's own AI answer — they reference a
            # different numbering scheme and would cause out-of-range citations.
            content = self._strip_sources_section(result.full_content)
            content = self._strip_inline_citations(content)
            lines.append(f"\n{content}\n")

            # Gather sources from metadata — may be a list of dicts or strings
            for src in result.metadata.get("sources", []):
                if isinstance(src, dict):
                    url = src.get("url", "")
                    title = src.get("title", url)
                else:
                    # Plain URL string (legacy / other tools)
                    url = str(src)
                    title = url
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_sources.append({"url": url, "title": title})

        # Append deduplicated source list so the LLM can build inline citations
        if all_sources:
            n = len(all_sources)
            lines.append(f"\n# Available Sources — {n} total (ONLY these {n} sources exist)")
            lines.append(
                f"CRITICAL: The source list below contains exactly {n} entries numbered "
                f"[1] through [{n}]. You MUST NOT use any citation number outside this "
                f"range. Any [n] where n > {n} is invalid and must not appear in your report."
            )
            for j, src in enumerate(all_sources, 1):
                title = src.get("title", "Untitled")
                url = src.get("url", "")
                lines.append(f"[{j}] {title} — {url}")

        lines.append("\n# Instructions")
        if all_sources:
            n = len(all_sources)
            lines.append(
                "Synthesize the above research results into a comprehensive, "
                "well-structured report that addresses the research goal. "
                f"Use [n] inline citations where n is between 1 and {n} (inclusive). "
                f"NEVER use a citation number greater than {n} — the source list has "
                f"exactly {n} entries and there are no others. "
                "Include a ## Sources section at the end listing only the sources you actually cited."
            )
        else:
            lines.append(
                "Synthesize the above research results into a comprehensive, "
                "well-structured report that addresses the research goal. "
                "No source URLs were collected for this session, so do NOT include "
                "any inline citations ([n]) or a Sources section in your report."
            )

        source_count = len(all_sources)
        return "\n".join(lines), source_count

    @staticmethod
    def _count_emitted_sources(report: str) -> int:
        """Count numbered entries in the LLM-emitted ## Sources section.

        The LLM writes a ``## Sources`` section at the end of the report
        listing only the sources it actually cited, numbered from 1.  This
        count is the ground truth for valid citation indices: any ``[n]``
        in the body where ``n`` exceeds this count is a dangling reference
        that must be stripped.

        If no Sources section is found, returns 0 (caller falls back to the
        prompt source count).

        Args:
            report: The synthesized report text

        Returns:
            Number of entries found in the ## Sources section, or 0
        """
        import re
        # Locate the ## Sources section (exact heading, as written by the LLM)
        match = re.search(
            r'\n#{1,6}\s+Sources\s*[.:]?\s*$(.*)$',
            report,
            flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
        )
        if not match:
            return 0
        sources_block = match.group(1)
        # Count lines that look like numbered entries: "  1 Title" or "1. Title"
        entries = re.findall(r'^\s*\d+[\.\):]?\s+\S', sources_block, flags=re.MULTILINE)
        return len(entries)

    @staticmethod
    def _remove_out_of_range_citations(report: str, source_count: int) -> str:
        """Strip any inline citation [n] where n > source_count from the report.

        The LLM sometimes generates citation numbers beyond the valid range
        despite explicit prompt instructions.  This post-processing step
        enforces the constraint deterministically so the final report never
        contains a reference to a non-existent source.

        Args:
            report: The synthesized report text
            source_count: Number of valid sources (1-indexed up to this value)

        Returns:
            Report with all out-of-range [n] markers removed
        """
        import re

        def _replace(m: re.Match) -> str:
            n = int(m.group(1))
            return m.group(0) if n <= source_count else ""

        return re.sub(r'\[(\d+)\]', _replace, report)

    @staticmethod
    def _strip_inline_citations(content: str) -> str:
        """Remove pre-existing [n] citation markers from tool output.

        Tavily's AI answer may itself contain [n] references that are
        unrelated to our global source list.  Leaving them in causes the
        LLM to treat them as valid citation numbers, producing out-of-range
        references in the final report.

        Args:
            content: Raw full_content string from a ToolResult

        Returns:
            Content with all [<digits>] markers removed
        """
        import re
        return re.sub(r'\[\d+\]', '', content)

    @staticmethod
    def _strip_sources_section(content: str) -> str:
        """Remove a trailing '## Sources' (or '# Sources') block from tool output.

        Guards against any tool that still emits a ``## Sources`` heading.
        WebSearchTool now uses ``## Search Result Summaries`` instead, so this
        is a safety net for legacy or third-party tools.  Stripping any literal
        Sources heading keeps citation authority solely with the global list
        built from ``metadata["sources"]``.

        Args:
            content: Raw full_content string from a ToolResult

        Returns:
            Content with the Sources section removed
        """
        import re
        # Match a markdown heading whose text is exactly "Sources" (case-insensitive),
        # optionally followed by trailing punctuation/whitespace but NOT further words.
        # This prevents false matches such as "## Sources of revenue" from stripping
        # legitimate content that follows such a heading.
        # (?:\n|^) lets the pattern also match a heading at byte 0 (no preceding newline).
        stripped = re.sub(
            r'(?:\n|^)#{1,6}\s+Sources\s*[.:]?\s*$.*',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
        )
        return stripped.rstrip()
