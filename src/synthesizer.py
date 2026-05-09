"""Synthesizer that creates final reports from research results."""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI

from .context import estimate_tokens
from .models import ToolResult

if TYPE_CHECKING:
    from .cli import CLI


@dataclass
class SynthesisContextStats:
    """Statistics about synthesis context construction."""

    total_tokens: int
    results_with_full_content: int  # includes partial full content
    results_summary_only: int  # no full content at all
    truncation_occurred: bool  # any truncation (summary or full content)
    omitted_results: int  # results omitted due to budget exhaustion


@dataclass
class ResultBlock:
    """One included synthesis result block plus its accounting metadata."""

    lines: list[str]
    tokens: int
    result_index: int
    kind: str


@dataclass
class SourceCollection:
    """Unique sources collected from included result blocks."""

    entries: list[dict[str, Any]]
    section: str


class Synthesizer:
    """Synthesizes research results into coherent final reports."""

    def __init__(
        self,
        api_key: str | None = None,
        cli: "CLI | None" = None,
        input_token_budget: int = 100_000,
    ):
        """Initialize synthesizer.

        Args:
            api_key: OpenAI API key
            cli: CLI interface for logging (optional)
            input_token_budget: Maximum tokens for synthesis input (default 100K)
        """
        self.client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.1")
        self.cli = cli
        self.input_token_budget = input_token_budget

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
            if self.cli:
                self.cli.show_info(f"Preparing {len(results)} research results for synthesis...")
            context, source_count, stats = self._build_context(goal, results)

            if self.cli:
                if source_count > 0:
                    self.cli.show_info(f"Collected {source_count} unique sources for citation")
                self.cli.show_info(
                    f"Synthesis context: {stats.total_tokens} tokens, "
                    f"{stats.results_with_full_content} with full content, "
                    f"{stats.results_summary_only} summary-only"
                )
                if stats.omitted_results > 0:
                    self.cli.show_warning(
                        f"⚠️  {stats.omitted_results} results omitted due to budget exhaustion"
                    )
                if stats.truncation_occurred:
                    self.cli.show_info("⚠️  Content truncated to fit synthesis budget")
                self.cli.show_info(f"Generating comprehensive report using {self.model}...")

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

            if self.cli:
                self.cli.show_info("Report generated, validating citations...")

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

            if self.cli:
                self.cli.show_info("Synthesis complete")

            return report

        except Exception as e:
            raise ValueError(f"Failed to synthesize report: {e}")

    def _build_context(
        self, goal: str, results: list[ToolResult]
    ) -> tuple[str, int, SynthesisContextStats]:
        """Build context for synthesis with token budget enforcement.

        Args:
            goal: The research goal
            results: All tool results

        Returns:
            Tuple of (formatted context string, number of unique sources, stats)
        """
        header = self._render_header(goal, len(results))
        initial_fixed = self._estimate_initial_fixed_tokens(header)
        remaining_budget = self._remaining_budget_for_results(initial_fixed)

        result_blocks: list[ResultBlock] = []
        included_result_indices: list[int] = []
        results_with_full_content = 0
        results_summary_only = 0
        truncation_occurred = False
        current_tokens = 0

        for i, result in enumerate(results, 1):
            block, was_truncated = self._build_result_block(result, i, current_tokens, remaining_budget)
            if block is None:
                truncation_occurred = True
                omitted_count = len(results) - (i - 1)
                if self.cli:
                    self.cli.show_warning(
                        f"⚠️  Synthesis budget exhausted after {i-1}/{len(results)} results. "
                        f"Remaining {omitted_count} results omitted."
                    )
                break
            result_blocks.append(block)
            current_tokens += block.tokens
            included_result_indices.append(block.result_index)
            truncation_occurred = truncation_occurred or was_truncated
            if block.kind == "full":
                results_with_full_content += 1
            else:
                results_summary_only += 1

        source_collection = self._collect_sources(results, included_result_indices)
        instructions = self._render_instructions(len(source_collection.entries))
        fixed_tokens = self._calculate_fixed_tokens(header, source_collection.section, instructions)

        while fixed_tokens + current_tokens > self.input_token_budget and result_blocks:
            removed_block = result_blocks.pop()
            current_tokens -= removed_block.tokens
            included_result_indices.remove(removed_block.result_index)

            if removed_block.kind == "full" and results_with_full_content > 0:
                results_with_full_content -= 1
            elif removed_block.kind in ("summary", "minimal") and results_summary_only > 0:
                results_summary_only -= 1

            truncation_occurred = True
            source_collection = self._collect_sources(results, included_result_indices)
            instructions = self._render_instructions(len(source_collection.entries))
            fixed_tokens = self._calculate_fixed_tokens(
                header, source_collection.section, instructions
            )

            if self.cli:
                self.cli.show_info(
                    f"Trimmed 1 result to enforce hard budget cap (now {fixed_tokens + current_tokens} tokens)"
                )

        if not result_blocks and len(results) > 0:
            raise ValueError(
                f"Synthesis budget ({self.input_token_budget} tokens) is insufficient "
                f"to include even one result with its sources. "
                f"Increase input_token_budget."
            )

        result_lines = self._flatten_result_blocks(result_blocks)
        context = "\n".join([header] + result_lines + [source_collection.section, instructions])
        total_tokens = fixed_tokens + current_tokens
        included_results = results_with_full_content + results_summary_only
        omitted_results = len(results) - included_results

        stats = SynthesisContextStats(
            total_tokens=total_tokens,
            results_with_full_content=results_with_full_content,
            results_summary_only=results_summary_only,
            truncation_occurred=truncation_occurred,
            omitted_results=omitted_results,
        )

        return context, len(source_collection.entries), stats

    def _render_header(self, goal: str, result_count: int) -> str:
        """Render the fixed synthesis header."""
        return "\n".join(
            [
                f"# Research Goal\n{goal}\n",
                "# Research Results\n",
                f"Total tasks completed: {result_count}\n",
            ]
        )

    def _estimate_initial_fixed_tokens(self, header: str) -> int:
        """Estimate fixed prompt overhead before sources are known."""
        instruction_base = (
            "\n# Instructions\nSynthesize the above research results into a "
            "comprehensive, well-structured report that addresses the research goal."
        )
        return (
            estimate_tokens(self.system_prompt)
            + estimate_tokens(header)
            + estimate_tokens(instruction_base)
            + 200
        )

    def _remaining_budget_for_results(self, initial_fixed: int) -> int:
        """Return the budget left for result blocks after fixed prompt costs."""
        if initial_fixed >= self.input_token_budget:
            raise ValueError(
                f"Synthesis budget ({self.input_token_budget} tokens) is insufficient "
                f"for minimal prompt components ({initial_fixed} tokens)."
            )
        return self.input_token_budget - initial_fixed

    def _build_result_block(
        self,
        result: ToolResult,
        result_number: int,
        current_tokens: int,
        remaining_budget: int,
    ) -> tuple[ResultBlock | None, bool]:
        """Build the largest allowed block for a single result."""
        status = "Success" if result.success else "Failed"
        summary, summary_truncated = self._cap_summary(result.summary)
        minimum_lines = [
            f"## Result {result_number}: Task {result.task_id}",
            f"Tool: {result.tool_name}",
            f"Status: {status}",
            f"Summary: {summary}",
        ]
        minimum_text = "\n".join(minimum_lines)
        minimum_tokens = estimate_tokens(minimum_text)
        content = self._clean_full_content(result.full_content)
        content_tokens = estimate_tokens(content)
        full_block = ResultBlock(
            lines=minimum_lines + [f"\n{content}\n"],
            tokens=minimum_tokens + content_tokens,
            result_index=result_number - 1,
            kind="full",
        )
        if current_tokens + full_block.tokens <= remaining_budget:
            return full_block, summary_truncated

        summary_line = "[Full content omitted due to synthesis budget]\n"
        summary_block = ResultBlock(
            lines=minimum_lines + [summary_line],
            tokens=minimum_tokens + estimate_tokens(summary_line),
            result_index=result_number - 1,
            kind="summary",
        )
        if current_tokens + summary_block.tokens <= remaining_budget:
            return summary_block, True

        minimal_lines = [
            f"## Result {result_number}: Task {result.task_id}",
            f"Tool: {result.tool_name}",
            f"Status: {status}",
            "[Summary and content omitted due to synthesis budget]",
        ]
        minimal_block = ResultBlock(
            lines=minimal_lines,
            tokens=estimate_tokens("\n".join(minimal_lines)),
            result_index=result_number - 1,
            kind="minimal",
        )
        if current_tokens + minimal_block.tokens <= remaining_budget:
            return minimal_block, True

        return None, True

    def _cap_summary(self, summary: str) -> tuple[str, bool]:
        """Cap long summaries while preserving prior truncation wording."""
        if len(summary) <= 500:
            return summary, False
        return summary[:497] + "...[summary truncated]", True

    def _clean_full_content(self, content: str) -> str:
        """Normalize tool content before inclusion in synthesis."""
        return self._strip_inline_citations(self._strip_sources_section(content))

    def _collect_sources(
        self, results: list[ToolResult], included_result_indices: list[int]
    ) -> SourceCollection:
        """Collect unique metadata sources only from included result blocks."""
        all_sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for idx in included_result_indices:
            for src in results[idx].metadata.get("sources", []):
                normalized = self._normalize_source(src)
                if not normalized:
                    continue
                url = normalized["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_sources.append(normalized)

        return SourceCollection(
            entries=all_sources,
            section=self._render_source_section(all_sources),
        )

    def _normalize_source(self, source: Any) -> dict[str, str] | None:
        """Normalize metadata sources to title/url dictionaries."""
        if isinstance(source, dict):
            url = source.get("url", "")
            title = source.get("title", url)
        else:
            url = str(source)
            title = url
        if not url:
            return None
        return {"url": url, "title": title}

    def _render_source_section(self, sources: list[dict[str, str]]) -> str:
        """Render the authoritative source list for synthesis."""
        if not sources:
            return ""

        n = len(sources)
        lines = [f"\n# Available Sources — {n} total (ONLY these {n} sources exist)"]
        lines.append(
            f"CRITICAL: The source list below contains exactly {n} entries numbered "
            f"[1] through [{n}]. You MUST NOT use any citation number outside this "
            f"range. Any [n] where n > {n} is invalid and must not appear in your report."
        )
        for i, source in enumerate(sources, 1):
            lines.append(f"[{i}] {source.get('title', 'Untitled')} — {source.get('url', '')}")
        return "\n".join(lines)

    def _render_instructions(self, source_count: int) -> str:
        """Render synthesis instructions for the current source count."""
        instruction_lines = ["\n# Instructions"]
        if source_count > 0:
            instruction_lines.append(
                "Synthesize the above research results into a comprehensive, "
                "well-structured report that addresses the research goal. "
                f"Use [n] inline citations where n is between 1 and {source_count} (inclusive). "
                f"NEVER use a citation number greater than {source_count} — the source list has "
                f"exactly {source_count} entries and there are no others. "
                "Include a ## Sources section at the end listing only the sources you actually cited."
            )
        else:
            instruction_lines.append(
                "Synthesize the above research results into a comprehensive, "
                "well-structured report that addresses the research goal. "
                "No source URLs were collected for this session, so do NOT include "
                "any inline citations ([n]) or a Sources section in your report."
            )
        return "\n".join(instruction_lines)

    def _calculate_fixed_tokens(
        self, header: str, source_section: str, instructions: str
    ) -> int:
        """Calculate total fixed token overhead for the current prompt shape."""
        return (
            estimate_tokens(self.system_prompt)
            + estimate_tokens(header)
            + estimate_tokens(source_section)
            + estimate_tokens(instructions)
        )

    def _flatten_result_blocks(self, result_blocks: list[ResultBlock]) -> list[str]:
        """Flatten structured result blocks into prompt lines."""
        lines: list[str] = []
        for block in result_blocks:
            lines.extend(block.lines)
        return lines

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

        def _replace(m: re.Match[str]) -> str:
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
