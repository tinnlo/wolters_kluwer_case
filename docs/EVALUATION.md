# Evaluation Guide

This document describes the context management strategy, evaluation scenarios, and known trade-offs for the research agent.

---

## Context Management Strategy

The agent uses a **two-tier context approach** to balance detail preservation with token efficiency:

### Tier 1: Executor Context (Rolling Window)

During task execution, `ContextManager` maintains a rolling window of the last 5 tool results. For each new task, it builds a context dictionary containing:

- The overall research goal
- The current task description
- Status summary of all tasks in the plan
- Summaries (not full content) of the 5 most recent results

This context is passed to each tool via `Executor.execute_task()`. The window prevents unbounded token growth during long research sessions while keeping recent findings accessible.

**Current limitation**: `WebSearchTool` receives this context but does not currently use it for query refinement. A future enhancement could use recent result summaries to avoid duplicate queries or incorporate domain context from the goal.

### Tier 2: Synthesis Context (Budget-Controlled Full Content)

At synthesis time, `Synthesizer._build_context()` builds a comprehensive prompt that includes:

- System prompt (synthesis instructions)
- Research goal and user instructions
- Global source list (deduplicated from included results' `metadata["sources"]`)
- Task results with controlled content inclusion

**Token budget enforcement** (default 100,000 tokens):

The synthesizer accounts for all prompt components and enforces a hard budget cap:

1. **Initial result selection**: Results are selected using an estimated instruction token budget.

2. **Source collection**: Sources are collected only from results that were included in step 1.

3. **Hard cap enforcement**: After building the actual source list and instructions, if `fixed_tokens + current_tokens > input_token_budget`, results are trimmed from the end until the total is under budget.

4. **Per-result inclusion** (while budget allows):
   - Task ID, tool name, status (Success/Failed)
   - Summary capped at 500 characters (with `...[summary truncated]` if needed)
   - Either sanitized full content OR `[Full content omitted due to synthesis budget]`

5. **Full content inclusion** (conditional on remaining budget):
   - Inline citations `[n]` are stripped (prevents confusion with global source list)
   - Trailing `## Sources` sections are stripped (authority is the global list only)
   - Content is included if it fits within remaining budget
   - If budget is exhausted, only the minimum is included

6. **Hard cap termination**: If even an ultra-minimal entry (task ID + status only) would exceed the remaining budget, the loop terminates early and omits remaining results. The CLI logs: "⚠️  Synthesis budget exhausted after N/M results. Remaining K results omitted."

Token estimation uses a simple heuristic (4 characters per token) rather than a tokenizer library, trading accuracy for speed and zero dependencies.

---

## Evaluation Scenarios

### Scenario 1: Broad Current Topic

**Query**: "Research the current state of WebAssembly adoption"

**Success Criteria**:
- Plan generates 5-7 tasks covering multiple dimensions (adoption metrics, use cases, challenges, ecosystem)
- All tasks complete successfully with Tavily results
- Final report includes inline `[n]` citations for all factual claims
- `## Sources` section lists only cited sources (no uncited URLs)
- Report structure is coherent with clear sections
- No hallucinated claims (all statements traceable to sources)

**Expected Behavior**:
- Planner should decompose into subtasks: adoption metrics, major use cases, tooling/ecosystem, challenges/limitations, future outlook
- Each task should return 3-5 Tavily results with URLs
- Synthesis should produce a balanced report (1500-2500 words) with 8-15 unique sources
- Context budget should not trigger truncation (typical session uses ~40K tokens)

**How to Run**:
```bash
python main.py "Research the current state of WebAssembly adoption"
```

**What to Check**:
- `data/sessions.db` contains session with status `COMPLETED`
- Final report has `## Sources` section with numbered entries
- All `[n]` citations in body correspond to valid source numbers
- No `[Full content omitted due to synthesis budget]` markers (budget sufficient)

---

### Scenario 2: Comparative Analysis

**Query**: "Compare GraphQL vs REST APIs for mobile applications"

**Success Criteria**:
- Plan includes tasks for both GraphQL and REST characteristics
- At least 4 comparison dimensions covered (performance, caching, complexity, tooling, mobile-specific considerations)
- Report presents balanced trade-offs (not biased toward one approach)
- Clear structure with comparison sections or table
- Inline citations support claims about each technology

**Expected Behavior**:
- Planner should create separate tasks for GraphQL features, REST features, and mobile-specific considerations
- Synthesis should organize findings into a comparative structure
- Report should acknowledge context-dependent trade-offs (no "X is always better" claims)

**How to Run**:
```bash
python main.py "Compare GraphQL vs REST APIs for mobile applications"
```

**What to Check**:
- Report has sections for both technologies
- Trade-offs are explicitly discussed (pros/cons for each)
- Mobile-specific concerns (bandwidth, battery, offline support) are addressed
- Sources include documentation for both GraphQL and REST

---

### Scenario 3: Sparse/Ambiguous Topic

**Query**: "Research quantum computing applications in underwater basket weaving"

**Purpose**: Test agent behavior when evidence is sparse or non-existent.

**Success Criteria**:
- Agent does not crash or hang
- Plan is generated (even if tasks find limited results)
- Final report honestly acknowledges limited evidence
- Report includes explicit "Limitations" or "Insufficient Evidence" section
- No fabricated claims or hallucinated sources
- Sources (if any) are real URLs, not invented

**Expected Behavior**:
- Planner may generate 3-5 tasks attempting to find connections
- Tavily searches may return few or zero relevant results
- Synthesis should produce a short report (500-1000 words) stating:
  - "Limited evidence found for this topic"
  - "No direct applications documented in available sources"
  - Possibly tangential findings (quantum computing OR basket weaving separately)
- Report should NOT invent connections that don't exist in sources

**How to Run**:
```bash
python main.py "Research quantum computing applications in underwater basket weaving"
```

**What to Check**:
- Session completes without errors
- Report explicitly states evidence limitations
- No `[n]` citations pointing to non-existent sources
- `## Sources` section is empty or contains only tangentially related URLs
- Report tone is honest ("insufficient evidence") not speculative

---

### Scenario 4: Context Stress Test

**Purpose**: Verify synthesis context budget prevents overflow and tracks omitted results.

**Option A: Integration Test (Recommended)**

Create a test that simulates a long session with many large results:

```python
# tests/test_synthesizer.py
def test_synthesis_with_20_large_results():
    """Verify budget enforcement with 20 results of 10KB each."""
    synth = Synthesizer(api_key="test-key", input_token_budget=50_000)

    # Create 20 mock results with 10KB full_content each
    results = []
    for i in range(20):
        results.append(ToolResult(
            tool_name="web_search",
            task_id=f"task_{i}",
            success=True,
            summary=f"Summary for task {i}: " + ("X" * 400),
            full_content="Y" * 10_000,  # 10KB
            metadata={"sources": [{"url": f"https://example.com/{i}", "title": f"Source {i}"}]},
        ))

    context, source_count, stats = synth._build_context("Test goal", results)

    # Verify budget enforcement
    assert stats.total_tokens <= 50_000, "Budget exceeded"

    # Verify all included tasks are represented
    # Note: Hard cap may omit later results when budget exhausted
    included_count = stats.results_with_full_content + stats.results_summary_only
    for i in range(included_count):
        assert f"task_{i}" in context, f"Task {i} missing from context"

    # Verify omission is logged
    if stats.omitted_results > 0:
        assert stats.truncation_occurred, "Omission should set truncation flag"

    # Verify truncation occurred
    assert stats.truncation_occurred, "Expected truncation with 200KB of content"
    assert stats.results_summary_only > 0, "Expected some results to be summary-only"

    # Verify truncation markers present
    assert "[Full content omitted due to synthesis budget]" in context
```

**Success Criteria**:
- Test passes (budget enforced, included tasks present)
- `stats.total_tokens <= 50_000`
- All included task IDs appear in context (not necessarily all 20 due to hard cap)
- Truncation markers present for results that didn't fit
- If results are omitted, `stats.omitted_results > 0` and omission is logged

**Option B: Live Session with Interruption**

Run Scenario 1, interrupt mid-execution (Ctrl+C), then resume:

```bash
# Start session
python main.py "Research the current state of WebAssembly adoption"

# Press Ctrl+C after 2-3 tasks complete
# Note the session ID from output

# Resume
python main.py --resume <session-id>
```

**Success Criteria**:
- Resume completes remaining tasks
- Synthesis includes results from both pre-interruption and post-resume tasks
- Final report is coherent (no duplicate sections)
- Context manager rebuilds state correctly

**What to Check**:
- `data/sessions.db` shows tasks with different `updated_at` timestamps (before/after resume)
- Final report cites sources from all completed tasks
- No errors in synthesis phase

---

## Known Trade-offs and Limitations

### 1. Context Cleared on Resume

**Trade-off**: `ContextManager` is in-memory. On resume, the rolling window starts empty.

**Impact**: The first few tasks after resume have no prior-result context. If a tool were to use context for query refinement, it would lose that benefit immediately after resume.

**Mitigation**: Could persist the last N result summaries to SQLite and reload on resume. Not implemented due to:
- Current tools don't use context for query refinement
- Added complexity for marginal benefit
- Resume is primarily for failure recovery, not long-running sessions

### 2. Synthesis Budget Truncation

**Trade-off**: Full content is truncated when budget is exhausted, not semantically summarized.

**Impact**: For very long sessions (15+ tasks with large Tavily results), later task results may be represented by summary only. The synthesizer sees less detail for those tasks.

**Mitigation**:
- Default budget (100K tokens) handles typical sessions (5-10 tasks) without truncation
- Greedy inclusion policy prioritizes detail (full content) over task coverage
- Budget is configurable for longer sessions

**Why not semantic summarization?**: Would require additional LLM calls during synthesis, adding latency and cost. Character-based truncation is deterministic and fast.

### 3. Serial Execution Only

**Trade-off**: Tasks run one at a time, even when dependencies allow parallelization.

**Impact**: Plans with many independent branches take longer than necessary. A 10-task plan with 2 independent branches could theoretically run in ~50% of the time with parallel execution.

**Mitigation**: None currently. Serial execution was chosen for:
- Simpler implementation (no concurrency management)
- Easier debugging (deterministic execution order)
- Context window is small (5 results) and tasks frequently depend on prior results

**Future enhancement**: Could implement parallel execution for tasks with no dependencies or whose dependencies are all completed.

### 4. Single Tool Type

**Trade-off**: Only `WebSearchTool` is implemented. The architecture supports multiple tools (`ToolRegistry`, `Tool` ABC), but none are added beyond web search.

**Impact**: Agent cannot perform calculations, access databases, read local files, or execute code. All research is web-search-based.

**Mitigation**: None needed for take-home scope. The architecture is extensible; new tools can be added by:
1. Subclassing `Tool` ABC
2. Implementing `can_handle()` and `execute()`
3. Registering with `ToolRegistry`

### 5. Token Estimation Heuristic

**Trade-off**: Uses 4 chars/token heuristic instead of a tokenizer library (e.g., `tiktoken`).

**Impact**: Budget enforcement is approximate. Actual token count may vary by ±20% depending on text characteristics (code vs prose, punctuation density).

**Mitigation**: Budget has built-in headroom (100K budget for models with 128K+ context windows). Approximation error is acceptable for preventing overflow.

**Why not tiktoken?**: Adds dependency, slower, and precision is not critical for budget enforcement (we're preventing overflow, not optimizing to the last token).

---

## Time Spent

Based on git commit timestamps and development log:

- **Initial implementation** (planning, execution, synthesis, SQLite persistence): ~8 hours
- **Testing and refinement** (72 tests, edge cases, resume logic): ~4 hours
- **Context budget hardening** (token estimation, truncation, stats): ~2 hours
- **Documentation** (ARCHITECTURE.md, RUNNING.md, WALKTHROUGH.md, this file): ~3 hours
- **Code quality** (ruff, mypy, type annotations): ~1.5 hours

**Total**: ~18.5 hours

This includes time spent on:
- Learning OpenAI structured output API (new in GPT-4)
- Debugging Tavily API response format edge cases
- Iterating on synthesis prompt to improve citation accuracy
- Refining resume logic to handle `FAILED` task reset

---

## Recommendations for Further Evaluation

1. **Run all four scenarios** and inspect the final reports for:
   - Citation accuracy (all `[n]` correspond to valid sources)
   - Coherence (logical flow, no contradictions)
   - Completeness (all aspects of the goal addressed)

2. **Check SQLite state** after each scenario:
   ```bash
   sqlite3 data/sessions.db "SELECT session_id, goal, status FROM sessions;"
   sqlite3 data/sessions.db "SELECT id, status, result FROM tasks WHERE session_id='<id>';"
   ```

3. **Test resume robustness** by interrupting at different points:
   - During planning (should resume plan refinement and approval flow)
   - After 1 task (should resume and complete remaining tasks)
   - After all tasks but before synthesis (should synthesize immediately)

4. **Verify budget enforcement** by running the budget tests:
   ```bash
   pytest tests/test_synthesizer.py -k budget -v
   ```

   Key tests to verify:
   - `test_budget_enforcement_with_small_budget` - verifies hard cap with small budget
   - `test_budget_fixed_cost_overflow` - verifies failure when fixed costs exceed budget
   - `test_budget_all_minimums_retained` - verifies tasks are included while budget allows

5. **Inspect synthesis logs** for budget warnings:
   - Look for "⚠️  Content truncated to fit synthesis budget"
   - Check token estimates are reasonable (not wildly off from actual)
