# Research Agent

A goal-driven async research agent built from scratch for the Wolters Kluwer AI
Engineering take-home case study. No agent frameworks — pure Python with OpenAI and Tavily.

---

## What It Does

Given a natural-language research goal, the agent:

1. **Plans** — gpt-5.1 generates a dependency-aware task list (structured JSON output,
   validated by Pydantic).
2. **Executes** — runs each task in dependency order using registered tools (Tavily web
   search). State is persisted to SQLite after every step.
3. **Synthesises** — gpt-5.1 produces a Markdown report with inline `[n]` citations and
   a `## Sources` section, drawn from a deduplicated global source list built from
   Tavily result metadata.

Sessions can be listed and resumed after interruption without discarding partial results.

---

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# .env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...

python main.py "Research the current state of WebAssembly adoption"
```

See [docs/RUNNING.md](docs/RUNNING.md) for full installation and CLI reference.

---

## Session Management

```bash
# List past sessions
python main.py --list-sessions

# View a completed session's report
python main.py --view <session-id>

# Resume an interrupted session
python main.py --resume <session-id>

# Run with automatic plan approval (non-interactive)
python main.py --auto-approve "Research the current state of WebAssembly adoption"

# Show help and usage
python main.py --help
```

**To pause and resume a session:**
1. Press `Ctrl+C` during execution (session ID is shown at start)
2. Use `--list-sessions` to find the session ID if needed
3. Use `--resume <session-id>` to continue from where you left off

**Non-interactive execution:**
Use `--auto-approve` to automatically approve the generated plan without user confirmation. Useful for automated workflows, CI/CD, or generating transcripts programmatically.

**Regenerating transcripts:**
To generate a markdown transcript from any completed session:
```bash
python generate_transcript.py <session-id> [output-file]
# Example:
python generate_transcript.py 33389d05-6a93-4493-8135-94f760e677cf examples/transcript_webassembly.md
```

---

## Tests

```bash
python -m pytest tests/ -v   # 77 tests, all offline (no API calls)
```

---

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component map, data models, SQLite schema, design invariants |
| [docs/EVALUATION.md](docs/EVALUATION.md) | **Context strategy, evaluation scenarios, trade-offs** |
| [docs/RUNNING.md](docs/RUNNING.md) | Prerequisites, install, CLI usage, test commands |
| [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) | End-to-end trace: goal → plan → execute → synthesise |
| [examples/transcript_webassembly.md](examples/transcript_webassembly.md) | Real session transcript from live API calls |

---

## Context Management Strategy

The agent uses a **two-tier context approach** to balance detail preservation with token efficiency:

**During execution** (`ContextManager`): Maintains a rolling window of the last 5 tool result summaries. This prevents unbounded token growth during long sessions while keeping recent findings accessible to each new task.

**During synthesis** (`Synthesizer`): Enforces a hard token budget cap (default 100K) that accounts for system prompt, sources, and all task results. Results are included greedily (full content first) while budget allows. When budget is exhausted, the loop terminates and remaining results are omitted (logged to CLI). This prevents context overflow.

See [docs/EVALUATION.md](docs/EVALUATION.md) for detailed context strategy, evaluation scenarios, and known trade-offs.

---

## Project Structure

```
wolters_kluwer_case/
├── main.py                  CLI entry point
├── src/
│   ├── agent.py             Orchestration loop + resume()
│   ├── planner.py           gpt-5.1 → ResearchPlan
│   ├── synthesizer.py       gpt-5.1 → cited Markdown report
│   ├── executor.py          Task dispatch via ToolRegistry
│   ├── context.py           Rolling-window context builder
│   ├── state.py             SQLite persistence
│   ├── models.py            Pydantic models + enums
│   ├── cli.py               Rich terminal UI
│   ├── tools/
│   │   ├── base.py          Abstract Tool ABC
│   │   ├── registry.py      ToolRegistry
│   │   └── web_search.py    Tavily integration
│   └── prompts/
│       ├── planner.txt
│       └── synthesizer.txt
├── tests/                   72 pytest tests
├── docs/
│   ├── ARCHITECTURE.md
│   ├── EVALUATION.md
│   ├── RUNNING.md
│   ├── WALKTHROUGH.md
│   └── wolters_kluwer_case.md   Original take-home brief
├── examples/
│   └── transcript_webassembly.md
└── data/                    SQLite database (created at first run, gitignored)
```
