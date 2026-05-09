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
        # Build fixed header
        header_lines = [
            f"# Research Goal\n{goal}\n",
            "# Research Results\n",
            f"Total tasks completed: {len(results)}\n",
        ]
        header = "\n".join(header_lines)

        # Calculate budget for system prompt and header
        system_tokens = estimate_tokens(self.system_prompt)
        header_tokens = estimate_tokens(header)

        # Reserve budget for instructions (estimated without sources)
        instruction_base = "\n# Instructions\nSynthesize the above research results into a comprehensive, well-structured report that addresses the research goal."
        instruction_tokens = estimate_tokens(instruction_base) + 200  # Buffer for citation instructions

        # Initial fixed costs (without sources yet)
        initial_fixed = system_tokens + header_tokens + instruction_tokens

        # Check if even minimal fixed costs exceed budget
        if initial_fixed >= self.input_token_budget:
            raise ValueError(
                f"Synthesis budget ({self.input_token_budget} tokens) is insufficient "
                f"for minimal prompt components ({initial_fixed} tokens)."
            )

        # Remaining budget for results (sources will be added after)
        remaining_budget = self.input_token_budget - initial_fixed

        # Build results with budget enforcement, tracking which results are included
        result_blocks: list[tuple[list[str], int, int, str]] = []  # (lines, tokens, result_index, kind)
        included_result_indices = []  # Track which results made it into context
        results_with_full_content = 0
        results_summary_only = 0
        truncation_occurred = False
        current_tokens = 0

        for i, result in enumerate(results, 1):
            # Per-result minimum (always included)
            status = "Success" if result.success else "Failed"

            # Cap summary to 500 chars
            summary = result.summary
            if len(summary) > 500:
                summary = summary[:497] + "...[summary truncated]"
                truncation_occurred = True

            minimum_lines = [
                f"## Result {i}: Task {result.task_id}",
                f"Tool: {result.tool_name}",
                f"Status: {status}",
                f"Summary: {summary}",
            ]

            # Try to include full content if budget allows
            content = self._strip_sources_section(result.full_content)
            content = self._strip_inline_citations(content)

            minimum_text = "\n".join(minimum_lines)
            minimum_tokens = estimate_tokens(minimum_text)
            content_tokens = estimate_tokens(content)

            # Check if we can fit full content
            if current_tokens + minimum_tokens + content_tokens <= remaining_budget:
                # Include full content
                block_lines = minimum_lines + [f"\n{content}\n"]
                block_tokens = minimum_tokens + content_tokens
                result_blocks.append((block_lines, block_tokens, i - 1, "full"))
                current_tokens += block_tokens
                results_with_full_content += 1
                included_result_indices.append(i - 1)  # 0-indexed
            elif current_tokens + minimum_tokens + estimate_tokens("[Full content omitted due to synthesis budget]\n") <= remaining_budget:
                # Include minimum only
                block_lines = minimum_lines + ["[Full content omitted due to synthesis budget]\n"]
                block_tokens = minimum_tokens + estimate_tokens("[Full content omitted due to synthesis budget]\n")
                result_blocks.append((block_lines, block_tokens, i - 1, "summary"))
                current_tokens += block_tokens
                results_summary_only += 1
                truncation_occurred = True
                included_result_indices.append(i - 1)  # 0-indexed
            else:
                # Even minimum doesn't fit - include ultra-minimal entry
                minimal_lines = [
                    f"## Result {i}: Task {result.task_id}",
                    f"Tool: {result.tool_name}",
                    f"Status: {status}",
                    "[Summary and content omitted due to synthesis budget]",
                ]
                minimal_text = "\n".join(minimal_lines)
                minimal_tokens = estimate_tokens(minimal_text)

                # Hard cap: if even ultra-minimal would exceed budget, stop
                if current_tokens + minimal_tokens > remaining_budget:
                    # We've hit the absolute limit - cannot include more results
                    truncation_occurred = True
                    omitted_count = len(results) - (i - 1)
                    if self.cli:
                        self.cli.show_warning(
                            f"⚠️  Synthesis budget exhausted after {i-1}/{len(results)} results. "
                            f"Remaining {omitted_count} results omitted."
                        )
                    break

                result_blocks.append((minimal_lines, minimal_tokens, i - 1, "minimal"))
                current_tokens += minimal_tokens
                results_summary_only += 1
                truncation_occurred = True
                included_result_indices.append(i - 1)  # 0-indexed

        # Collect sources from initially included results
        all_sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for idx in included_result_indices:
            result = results[idx]
            for src in result.metadata.get("sources", []):
                if isinstance(src, dict):
                    url = src.get("url", "")
                    title = src.get("title", url)
                else:
                    url = str(src)
                    title = url
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_sources.append({"url": url, "title": title})

        # Build initial source list
        source_lines = []
        if all_sources:
            n = len(all_sources)
            source_lines.append(f"\n# Available Sources — {n} total (ONLY these {n} sources exist)")
            source_lines.append(
                f"CRITICAL: The source list below contains exactly {n} entries numbered "
                f"[1] through [{n}]. You MUST NOT use any citation number outside this "
                f"range. Any [n] where n > {n} is invalid and must not appear in your report."
            )
            for j, src in enumerate(all_sources, 1):
                title = src.get("title", "Untitled")
                url = src.get("url", "")
                source_lines.append(f"[{j}] {title} — {url}")
        source_section = "\n".join(source_lines)

        # Build initial instructions
        instruction_lines = ["\n# Instructions"]
        if all_sources:
            n = len(all_sources)
            instruction_lines.append(
                "Synthesize the above research results into a comprehensive, "
                "well-structured report that addresses the research goal. "
                f"Use [n] inline citations where n is between 1 and {n} (inclusive). "
                f"NEVER use a citation number greater than {n} — the source list has "
                f"exactly {n} entries and there are no others. "
                "Include a ## Sources section at the end listing only the sources you actually cited."
            )
        else:
            instruction_lines.append(
                "Synthesize the above research results into a comprehensive, "
                "well-structured report that addresses the research goal. "
                "No source URLs were collected for this session, so do NOT include "
                "any inline citations ([n]) or a Sources section in your report."
            )
        instructions = "\n".join(instruction_lines)

        # Calculate initial fixed tokens
        source_tokens = estimate_tokens(source_section)
        instruction_tokens_actual = estimate_tokens(instructions)
        fixed_tokens = system_tokens + header_tokens + source_tokens + instruction_tokens_actual

        # HARD CAP ENFORCEMENT: Trim complete results if fixed + current exceeds budget
        # This can happen because source tokens depend on included results, creating a circular dependency
        # We recalculate fixed_tokens inside the loop because removing results changes the source list
        while fixed_tokens + current_tokens > self.input_token_budget and result_blocks:
            # Remove the last complete result block
            removed_lines, removed_tokens, removed_idx, block_kind = result_blocks.pop()
            current_tokens -= removed_tokens
            included_result_indices.remove(removed_idx)

            # Update counters based on stored block kind
            if block_kind == "full" and results_with_full_content > 0:
                results_with_full_content -= 1
            elif block_kind in ("summary", "minimal") and results_summary_only > 0:
                results_summary_only -= 1

            truncation_occurred = True

            # Rebuild source list from remaining included results
            all_sources = []
            seen_urls = set()
            for idx in included_result_indices:
                result = results[idx]
                for src in result.metadata.get("sources", []):
                    if isinstance(src, dict):
                        url = src.get("url", "")
                        title = src.get("title", url)
                    else:
                        url = str(src)
                        title = url
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_sources.append({"url": url, "title": title})

            # Rebuild source section
            source_lines = []
            if all_sources:
                n = len(all_sources)
                source_lines.append(f"\n# Available Sources — {n} total (ONLY these {n} sources exist)")
                source_lines.append(
                    f"CRITICAL: The source list below contains exactly {n} entries numbered "
                    f"[1] through [{n}]. You MUST NOT use any citation number outside this "
                    f"range. Any [n] where n > {n} is invalid and must not appear in your report."
                )
                for j, src in enumerate(all_sources, 1):
                    title = src.get("title", "Untitled")
                    url = src.get("url", "")
                    source_lines.append(f"[{j}] {title} — {url}")
            source_section = "\n".join(source_lines)

            # Rebuild instructions with updated source count
            instruction_lines = ["\n# Instructions"]
            if all_sources:
                n = len(all_sources)
                instruction_lines.append(
                    "Synthesize the above research results into a comprehensive, "
                    "well-structured report that addresses the research goal. "
                    f"Use [n] inline citations where n is between 1 and {n} (inclusive). "
                    f"NEVER use a citation number greater than {n} — the source list has "
                    f"exactly {n} entries and there are no others. "
                    "Include a ## Sources section at the end listing only the sources you actually cited."
                )
            else:
                instruction_lines.append(
                    "Synthesize the above research results into a comprehensive, "
                    "well-structured report that addresses the research goal. "
                    "No source URLs were collected for this session, so do NOT include "
                    "any inline citations ([n]) or a Sources section in your report."
                )
            instructions = "\n".join(instruction_lines)

            # Recalculate fixed tokens with updated sources and instructions
            source_tokens = estimate_tokens(source_section)
            instruction_tokens_actual = estimate_tokens(instructions)
            fixed_tokens = system_tokens + header_tokens + source_tokens + instruction_tokens_actual

            if self.cli:
                self.cli.show_info(f"Trimmed 1 result to enforce hard budget cap (now {fixed_tokens + current_tokens} tokens)")

        # Check if we trimmed everything (but allow empty results list)
        if not result_blocks and len(results) > 0:
            raise ValueError(
                f"Synthesis budget ({self.input_token_budget} tokens) is insufficient "
                f"to include even one result with its sources. "
                f"Increase input_token_budget."
            )

        # Flatten result blocks into lines
        result_lines = []
        for block_lines, _, _, _ in result_blocks:
            result_lines.extend(block_lines)

        # Assemble final context
        context_parts = [header] + result_lines + [source_section, instructions]
        context = "\n".join(context_parts)

        # Calculate total tokens and omitted results
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

        return context, len(all_sources), stats

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
