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

# Resume an interrupted session
python main.py --resume <session-id>
```

---

## Tests

```bash
python -m pytest tests/ -v   # 51 tests, all offline (no API calls)
```

---

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component map, data models, SQLite schema, design invariants |
| [docs/RUNNING.md](docs/RUNNING.md) | Prerequisites, install, CLI usage, test commands |
| [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) | End-to-end trace: goal → plan → execute → synthesise |
| [examples/transcript_webassembly.md](examples/transcript_webassembly.md) | Annotated real run transcript |

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
├── tests/                   51 pytest tests
├── docs/
│   ├── ARCHITECTURE.md
│   ├── RUNNING.md
│   ├── WALKTHROUGH.md
│   └── wolters_kluwer_case.md   Original take-home brief
├── examples/
│   └── transcript_webassembly.md
└── data/                    SQLite database (created at first run, gitignored)
```
