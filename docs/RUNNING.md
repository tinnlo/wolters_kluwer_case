# Research Agent — Running

**Version:** 1.0.0
**Date:** 2026-05-08

---

## 1. Prerequisites

| Requirement | Minimum version | Notes |
|---|---|---|
| Python | 3.11 | `python3 --version` |
| pip | any recent | comes with Python |
| OpenAI API key | — | `OPENAI_API_KEY` env var |
| Tavily API key | — | `TAVILY_API_KEY` env var; free tier available at tavily.com |

Both API keys are required. The agent will fail at startup if either is missing.

---

## 2. Installation

```bash
git clone <repo-url>
cd wolters_kluwer_case

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install runtime dependencies
pip install -e .

# Install dev dependencies (required to run tests)
pip install -e ".[dev]"
```

---

## 3. Configuration

Create a `.env` file in the project root:

```dotenv
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

The agent reads this file automatically at startup via `python-dotenv`.

No other configuration is required. The SQLite database is created automatically at
`data/sessions.db` on first run.

---

## 4. Running a Research Session

### Interactive (prompts for goal)

```bash
python main.py
```

The agent prints a banner, prompts you to enter a research goal, then shows the generated
plan and asks for confirmation before executing.

### Non-interactive (goal as argument)

```bash
python main.py "What are the current trends in quantum computing?"
```

The goal is taken directly from the command line. The plan confirmation prompt still
appears — press `y` to proceed.

---

## 5. Session Management

### List past sessions

```bash
python main.py --list-sessions
```

Prints a table of all sessions with their ID, status, goal snippet, and creation time.

```
 Session ID                             Status        Goal
 ──────────────────────────────────────────────────────────
 3f2a1b4c-…                             completed     Research the current state of WebAssembly…
 9e8d7c6b-…                             failed        Analyse GPU market share trends
```

### Resume an interrupted session

```bash
python main.py --resume <session-id>
```

Re-runs only the pending and in-progress tasks from the specified session. Completed tasks
and their stored results are reused as-is for the final synthesis. Use this after a network
failure, API timeout, or manual interruption (`Ctrl+C`).

A session with status `completed` cannot be resumed (the stored report is already final).
Use `--list-sessions` to find the session ID.

---

## 6. Running Tests

```bash
python -m pytest tests/ -v
```

Expected output: **41 passed**. All tests are offline (no API calls); OpenAI and Tavily
clients are patched with `AsyncMock`.

```bash
# With coverage report
python -m pytest tests/ --cov=src --cov-report=term-missing
```

---

## 7. Linting and Type Checking

```bash
# Lint
ruff check src/ tests/

# Type check
mypy src/
```

---

## 8. Output

The synthesised report is printed to the terminal at the end of each session. It is also
persisted in `data/sessions.db` as `sessions.final_report` and can be retrieved via
`StateManager.get_session(session_id).final_report`.

There is no file export — the terminal output is the intended artifact for the take-home
scope.
