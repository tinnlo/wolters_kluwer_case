# Research Agent — Architecture

**Version:** 1.0.0
**Date:** 2026-05-08
**Audience:** Technical reviewers, future contributors

---

## 1. Purpose

This system is a minimal, framework-free async research agent. Given a natural-language goal
it generates a dependency-aware task plan, executes each task against real tools, and
synthesises a cited Markdown report. All state is persisted in SQLite so sessions can be
listed and resumed after interruption.

The design priority is legibility: every component has a single clear responsibility, there are
no implicit side effects between components, and all persistence is in a human-inspectable
local database.

---

## 2. Core Design Principle: Agent Orchestrates, Tools Execute

```mermaid
graph TD
    USER["👤 User Goal<br>Natural-language research objective"]

    subgraph PHASE1["Phase 1 · Planning"]
        PLAN["Planner<br>gpt-5.1 · structured JSON output"]
        MODEL["ResearchPlan<br>Pydantic model · tasks + dependency graph"]
        CONFIRM{"User confirms?"}
        CANCEL["Session → CANCELLED"]
    end

    subgraph PHASE2["Phase 2 · Execution"]
        LOOP["Agent Loop<br>get_next_task · dependency-ordered"]
        CTX["ContextManager<br>rolling window · last 5 results"]
        EXEC["Executor<br>dispatches to ToolRegistry"]
        TOOL["WebSearchTool<br>Tavily API · returns titled sources"]
    end

    subgraph STORE["State · SQLite"]
        DB[("sessions<br>tasks · tool_results · logs")]
    end

    subgraph PHASE3["Phase 3 · Synthesis"]
        SYNTH["Synthesizer<br>gpt-5.1 · global source list · inline [n] citations"]
        REPORT["Final Report<br>Markdown · status = COMPLETED"]
    end

    USER --> PLAN --> MODEL --> CONFIRM
    CONFIRM -- yes --> LOOP
    CONFIRM -- no --> CANCEL
    LOOP --> CTX
    LOOP --> EXEC --> TOOL --> DB
    DB --> LOOP
    DB --> SYNTH --> REPORT

    classDef usernode  fill:#e8eaf6,stroke:#3949ab,stroke-width:2px
    classDef planning  fill:#e6f0ff,stroke:#003399,stroke-width:1px
    classDef execution fill:#fff3cd,stroke:#b8860b,stroke-width:1px
    classDef storage   fill:#fce8ff,stroke:#7b2fa8,stroke-width:1px
    classDef synthesis fill:#d4edda,stroke:#155724,stroke-width:1px
    classDef cancel    fill:#ffe6e6,stroke:#b30000,stroke-width:1px

    class USER usernode
    class PLAN,MODEL,CONFIRM planning
    class LOOP,CTX,EXEC,TOOL execution
    class DB storage
    class SYNTH,REPORT synthesis
    class CANCEL cancel

    style PHASE1 fill:transparent,stroke:#999,stroke-width:1px,stroke-dasharray:4 4
    style PHASE2 fill:transparent,stroke:#999,stroke-width:1px,stroke-dasharray:4 4
    style STORE  fill:transparent,stroke:#999,stroke-width:1px,stroke-dasharray:4 4
    style PHASE3 fill:transparent,stroke:#999,stroke-width:1px,stroke-dasharray:4 4
```

The LLM is used in exactly two places:

- **Planner** — generates the task list and dependency graph from the goal.
- **Synthesizer** — produces the final report from tool outputs.

It is not used to decide which tool to call, to validate results, or to interpret errors.
Those paths are deterministic Python.

---

## 3. Component Map

```
wolters_kluwer_case/
├── main.py                 CLI entry point; --list-sessions, --resume, positional goal
├── src/
│   ├── agent.py            Agent controller: run() and resume() orchestration loops
│   ├── planner.py          AsyncOpenAI call → ResearchPlan (structured output)
│   ├── synthesizer.py      AsyncOpenAI call → cited Markdown report (with CLI logging)
│   ├── executor.py         Task dispatch via ToolRegistry; status transitions
│   ├── context.py          Rolling-window context builder (last N results)
│   ├── state.py            SQLite persistence: sessions, tasks, tool_results, logs
│   ├── cli.py              Rich terminal UI (display, prompts, progress)
│   ├── models.py           Pydantic models + SessionStatus/TaskStatus enums
│   ├── tools/
│   │   ├── base.py         Abstract Tool ABC (name, description, can_handle, execute)
│   │   ├── registry.py     ToolRegistry: register/dispatch by name
│   │   └── web_search.py   WebSearchTool: Tavily API wrapper
│   └── prompts/
│       ├── planner.txt     Planning system prompt
│       └── synthesizer.txt Synthesis system prompt (instructs inline citations)
├── tests/                  pytest suite — 77 tests
├── data/                   SQLite database (created at first run)
└── examples/               Annotated run transcripts
```

---

## 4. Data Models

All models are Pydantic v2. The enums prevent magic-string bugs across the codebase.

| Model | Purpose | Key fields |
|---|---|---|
| `Task` | A single unit of work | `id`, `description`, `status: TaskStatus`, `dependencies: list[str]` |
| `ResearchPlan` | LLM-generated plan | `goal`, `tasks: list[Task]` |
| `ToolResult` | Tool execution output | `task_id`, `success`, `summary`, `full_content`, `metadata` |
| `AgentSession` | Full session record | `session_id`, `goal`, `plan`, `final_report`, `status: SessionStatus` |
| `LogEntry` | Structured audit log | `level: Literal["INFO","WARNING","ERROR"]`, `component`, `message` |

**`SessionStatus` lifecycle:**

```mermaid
stateDiagram-v2
    [*] --> PLANNING : session created
    PLANNING --> CANCELLED : user rejected plan
    PLANNING --> EXECUTING : user confirmed plan
    EXECUTING --> SYNTHESIZING : all tasks finished
    SYNTHESIZING --> COMPLETED : report saved
    EXECUTING --> FAILED : unhandled exception
    SYNTHESIZING --> FAILED : no successful results
    PLANNING --> INTERRUPTED : user pressed Ctrl+C
    EXECUTING --> INTERRUPTED : user pressed Ctrl+C
    SYNTHESIZING --> INTERRUPTED : user pressed Ctrl+C
    INTERRUPTED --> EXECUTING : --resume (continues from where stopped)
```

**Status semantics:**
- **FAILED**: Actual errors, exceptions, or unrecoverable issues
- **INTERRUPTED**: User intentionally stopped the session (Ctrl+C); can be resumed
- **CANCELLED**: User rejected the plan during planning phase

**`TaskStatus` lifecycle:**

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> IN_PROGRESS : executor picks up task
    IN_PROGRESS --> COMPLETED : tool success
    IN_PROGRESS --> FAILED : tool error / exception
    PENDING --> FAILED : dependency failed (blocked)
```

---

## 5. Persistence Schema

Four SQLite tables in `data/sessions.db`:

```
sessions
  session_id TEXT PK
  goal, plan_json, final_report, status, created_at, completed_at

tasks
  (session_id, id)  COMPOSITE PK
  description, status, dependencies_json, tool_name, result, error
  FK → sessions(session_id)

tool_results
  id INTEGER PK AUTOINCREMENT
  tool_name, task_id, session_id, success, summary, full_content, metadata_json
  FK → tasks(session_id, id)
  FK → sessions(session_id)

logs
  id INTEGER PK AUTOINCREMENT
  session_id, timestamp, level, component, message, metadata_json
  FK → sessions(session_id)
```

The composite primary key on `tasks` (`session_id`, `id`) is required because task IDs are
only unique within a session. `tool_results` references both columns to maintain referential
integrity.

---

## 6. Execution Order and Dependency Resolution

`StateManager.get_next_task()` scans tasks in insertion order and returns the first
`PENDING` task whose every dependency `task_id` has `status == COMPLETED`. Tasks with
unmet dependencies are skipped in the current pass.

If `get_next_task()` returns `None` while `has_pending_tasks()` is still true, remaining
pending tasks have failed dependencies. They are force-failed with
`error="Blocked by failed dependencies"` and the loop terminates.

This is a simple topological walk, not a full DAG scheduler. It is deliberately serial:
the context window is small and tasks frequently depend on prior results.

---

## 7. Context Window Strategy

`ContextManager` keeps a rolling window of the last `max_recent_results` (default 5)
tool results. For each new task it builds a `dict` containing:

- the overall goal
- the current task descriptor
- a status summary of all tasks in the plan
- summaries of the N most recent results

This context is passed to `Executor.execute_task()` and forwarded to the tool. For
`WebSearchTool` the context is available but currently unused in query construction
(a future enhancement could use recent results to avoid duplicate queries or add
domain context from the goal). The window prevents token growth proportional to
session length while preserving the most relevant recent findings.

---

## 8. Source Attribution

The synthesizer prompt instructs the LLM to use inline `[n]` citations and append a
`## Sources` section. The source list is built deterministically in
`Synthesizer._build_context()`:

1. Iterate `ToolResult.metadata["sources"]` entries for results actually included in the synthesis context (after budget enforcement).
2. Deduplicate by URL.
3. Emit a numbered list `[1] Title — URL` before the synthesis instructions.

`metadata["sources"]` may contain either `dict` objects (`{"url": …, "title": …}`) or
plain URL strings. Both are handled.

### 8.1 Synthesis Progress Logging

The `Synthesizer` accepts an optional `CLI` instance for progress logging during the
synthesis phase, which typically takes 15-25 seconds. When a CLI is provided, the
synthesizer displays:

1. **Preparation** — "Preparing N research results for synthesis..."
2. **Source count** — "Collected N unique sources for citation" (if sources exist)
3. **API call start** — "Generating comprehensive report using {model}..."
4. **Post-processing** — "Report generated, validating citations..."
5. **Completion** — "Synthesis complete"

This provides observability into the synthesis process without requiring the user to
wait in silence. The CLI parameter is optional; tests instantiate `Synthesizer()`
without it.

### 8.2 Synthesis Context Budget

The `Synthesizer` enforces a configurable token budget (default 100,000 tokens) to
prevent context window overflow during synthesis. The budget accounts for:

- System prompt
- Research goal and instructions
- Global source list (deduplicated from included results' `metadata["sources"]`)
- All task results (minimums + full content where budget allows)

**Budget enforcement is a hard cap**: Sources are collected only from results that fit
within the initial budget estimate. After source collection, if `fixed_tokens + current_tokens`
exceeds the budget, results are trimmed from the end until the total is under budget.
This ensures the final prompt never exceeds `input_token_budget`.

**Per-result minimum** (included while budget allows):
- Task ID, tool name, status (Success/Failed)
- Summary (capped at 1000 characters with `...[summary truncated]` marker if needed)
- Either sanitized `full_content` OR `[Full content omitted due to synthesis budget]`

**Full content inclusion** (conditional on remaining budget):
- Inline citations `[n]` are stripped (prevents confusion with global source list)
- Trailing `## Sources` sections are stripped (authority is the global list only)
- Content is included if it fits within remaining budget after accounting for the minimum
- If even the minimum doesn't fit, an ultra-minimal entry is included (task ID + status only)
- If even ultra-minimal would exceed budget, the loop terminates and remaining results are omitted

The budget is configurable via the `input_token_budget` parameter to `Synthesizer.__init__()`,
enabling deterministic testing with small budgets (e.g., 2,000 tokens) to trigger
truncation. Token estimation uses `tiktoken` for accurate token counting with a fallback
to a simple heuristic (4 characters per token) if tiktoken fails.

When truncation occurs, the CLI logs:
- Total estimated prompt tokens
- Number of results with full content vs summary-only
- A warning: "⚠️  Content truncated to fit synthesis budget"

When the budget is exhausted before all results are included, the CLI logs:
- "⚠️  Synthesis budget exhausted after N/M results. Remaining K results omitted."

---

## 10. Session Resume

`Agent.resume(session_id)`:

1. Loads the existing session. Raises `ValueError` if the session:
   - does not exist,
   - is `COMPLETED` (`"already completed"`), or
   - is `CANCELLED` (`"was cancelled by the user"`)
2. If status is `PLANNING`, resumes plan refinement and approval flow. If a plan exists, displays it for approval; otherwise generates a new plan.
3. If status is `EXECUTING`, `SYNTHESIZING`, `INTERRUPTED`, or `FAILED`, resets any `IN_PROGRESS` **or `FAILED`** tasks to `PENDING`. `FAILED` tasks are reset because the primary resume use-case is transient network/API failure; without this reset, `--resume` would be a no-op for the most common failure mode.
4. Re-enters the appropriate phase (planning, execution, or synthesis) and continues from where it left off, reusing all `COMPLETED` task results already in `tool_results`.

This allows recovery from network failures, API rate limits, or manual interruption (Ctrl+C) without discarding partial work. When a user interrupts a session with Ctrl+C, the status is set to `INTERRUPTED` (not `FAILED`), clearly distinguishing intentional stops from actual errors.

---

## 11. What Was Deliberately Left Out

| Feature | Reason |
|---|---|
| Agent framework (LangChain, LangGraph, etc.) | Adds abstraction without benefit for a single-tool serial loop |
| Parallel task execution | Context window strategy assumes serial, dependency-ordered results |
| Vector store / RAG | Not needed; full text is stored in `tool_results.full_content` |
| Streaming output | Terminal UI uses Rich panels; streaming adds complexity for no UX gain |
| Additional tool types | Tavily covers the take-home scope; registry pattern supports future addition |
| Web UI / REST API | Out of scope |

---

## 12. Known Gaps

- **Single tool type:** Only `WebSearchTool` is registered. The `ToolRegistry` and
  `Tool` ABC support additional tools; none are implemented beyond the take-home scope.

- **No parallel execution:** Tasks run serially. High-dependency-count plans with many
  independent branches are slower than necessary.

- **Context cleared on resume:** `ContextManager` is in-memory. On resume the rolling
  window starts empty; the first few tasks after resume have no prior-result context.
  Completed result summaries are not pre-loaded into the window.
