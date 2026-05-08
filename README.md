# AI Research Assistant

A goal-driven AI agent that breaks down complex research tasks into actionable steps and executes them using real tools. Built from scratch without agent frameworks for the Wolters Kluwer AI Engineering take-home case study.

## Overview

This system demonstrates a complete AI agent loop:
1. **Planning**: Converts high-level research goals into structured task plans
2. **Execution**: Executes tasks using real tools (web search via Tavily API)
3. **Synthesis**: Combines results into comprehensive research reports

## Architecture

### Component Flow

```
User Goal → Planner → Task Plan → Executor → Tool Results → Synthesizer → Final Report
                ↓                      ↓              ↓
            SQLite DB ←────────────────┴──────────────┘
```

### Core Components

**Agent Controller** (`src/agent.py`)
- Orchestrates the complete research workflow
- Manages session lifecycle and error handling
- Coordinates between all components

**Planner** (`src/planner.py`)
- Uses GPT-4o to convert goals into structured task plans
- Validates task dependencies and detects circular references
- Generates 5-7 specific, actionable tasks per goal

**Executor** (`src/executor.py`)
- Dispatches tasks to appropriate tools
- Tracks task status (pending → in_progress → completed/failed)
- Manages execution context

**Tool System** (`src/tools/`)
- Abstract `Tool` base class for extensibility
- `ToolRegistry` for tool selection and dispatch
- `WebSearchTool` using Tavily API for AI-optimized search

**Synthesizer** (`src/synthesizer.py`)
- Uses GPT-4o to create coherent final reports
- Combines multiple tool results with proper citations
- Generates markdown-formatted research reports

**State Manager** (`src/state.py`)
- SQLite-based persistence for sessions, tasks, and results
- Enables transparent logging and audit trails
- Supports dependency resolution for task ordering

**Context Manager** (`src/context.py`)
- Manages LLM context to avoid token overflow
- Keeps recent results (last 5) in active context
- Stores full results in SQLite for synthesis

**CLI** (`src/cli.py`)
- Rich-based terminal interface with colors and formatting
- Real-time progress tracking
- Interactive plan confirmation

## Context Management Strategy

### The Challenge
Research tasks accumulate context: goal + plan + tool results + synthesis. Without management, this quickly exceeds token limits and increases costs.

### Solution: Tiered Storage + Selective Context

**What Goes in LLM Context:**
- System instructions and role definition
- Original user goal
- Complete task plan structure (IDs, descriptions, dependencies)
- Current task being executed
- Recent task results (last 5, summarized)

**What Goes in SQLite (Not in LLM Context):**
- Full tool results with complete content
- All task execution logs
- Task status transitions
- Detailed error messages

**Benefits:**
- Executor sees recent context for informed decisions
- Synthesizer reads full results from SQLite for comprehensive reports
- Token usage stays manageable (typically < 10K per request)
- Complete audit trail preserved in database

## Tools Integrated

### Web Search (Tavily API) - Required
- AI-optimized search for research tasks
- Returns clean, structured results with sources
- Includes AI-generated answers for quick insights
- Handles rate limiting and errors gracefully

**Example Usage:**
```python
task = Task(
    id="task-1",
    description="Search for WebAssembly adoption statistics",
    dependencies=[]
)
result = await web_search_tool.execute(task, context)
# Returns: ToolResult with summary, full content, and source URLs
```

### Future Tools (Not Implemented)
- Web Scraper (Firecrawl) - Deep content extraction
- Document Reader - Local file processing
- Code Executor - Safe Python execution

## Installation & Setup

### Prerequisites
- Python 3.11+
- OpenAI API key
- Tavily API key

### Installation

```bash
# Clone repository
git clone <repository-url>
cd wolters_kluwer_case

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Configure API keys
cp .env.example .env
# Edit .env and add your API keys:
# OPENAI_API_KEY=your_key_here
# TAVILY_API_KEY=your_key_here
```

### Running the Agent

```bash
# Interactive mode (prompts for goal)
python main.py

# Command-line mode (provide goal as argument)
python main.py "Research the current state of WebAssembly adoption"
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_agent.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Evaluation Scenarios

### Scenario 1: Broad Technical Topic
**Goal:** "Research the current state of WebAssembly adoption"

**Expected Behavior:**
- Planner creates 5-7 tasks covering: definition, use cases, adoption metrics, implementations, trends
- Web search finds recent articles (2024-2026)
- Synthesizer creates coherent report with citations

**Success Criteria:**
- ✅ 100% task completion rate
- ✅ All sources from 2024-2026
- ✅ Comprehensive coverage (definition, adoption, use cases, trends)
- ✅ Proper citations and source attribution
- ✅ Execution time < 3 minutes

### Scenario 2: Comparative Analysis
**Goal:** "Compare GraphQL vs REST APIs for mobile applications"

**Expected Behavior:**
- Planner identifies comparison dimensions: performance, DX, ecosystem, use cases
- Tasks cover both technologies fairly
- Synthesizer provides balanced comparison with pros/cons

**Success Criteria:**
- ✅ 100% task completion rate
- ✅ Covers at least 4 comparison dimensions
- ✅ Balanced coverage (not biased)
- ✅ Clear recommendations based on use cases
- ✅ Execution time < 4 minutes

### Scenario 3: Emerging Technology
**Goal:** "Investigate recent developments in AI code generation tools"

**Expected Behavior:**
- Planner creates tasks for: landscape, recent releases, capabilities, limitations, trends
- Web search finds very recent information (2025-2026)
- Synthesizer highlights what's new and emerging

**Success Criteria:**
- ✅ 100% task completion rate
- ✅ All sources from 2025-2026
- ✅ Mentions at least 5 different tools
- ✅ Identifies recent developments (last 6 months)
- ✅ Execution time < 3 minutes

### Scenario 4: Error Recovery
**Goal:** "Research [intentionally obscure topic with limited results]"

**Expected Behavior:**
- Planner creates reasonable tasks despite limited information
- Web search returns few or no results
- Agent handles gracefully: tries alternative queries, reports limitations
- No hallucination of fake information

**Success Criteria:**
- ✅ Graceful degradation (doesn't crash)
- ✅ Clear error messages about limited information
- ✅ No hallucinated facts
- ✅ Suggests alternative approaches
- ✅ Execution time < 2 minutes

### Scenario 5: Complex Multi-Step Research
**Goal:** "Research security implications of using LLMs in production and mitigation best practices"

**Expected Behavior:**
- Planner creates 7-10 tasks covering: threats, vulnerabilities, mitigations, tools, case studies
- Tasks have logical dependencies (understand threats before mitigations)
- Synthesizer maintains coherence across many tasks
- Context management handles longer session

**Success Criteria:**
- ✅ 100% task completion rate
- ✅ Logical task ordering respected
- ✅ Final synthesis preserves key findings from earlier tasks
- ✅ Comprehensive coverage of security landscape
- ✅ Execution time < 5 minutes

## Design Decisions & Trade-offs

### 1. OpenAI API with Single Model
**Decision:** Use GPT-4o for all components (planning, execution, synthesis)

**Rationale:**
- GPT-5.4 not yet available, GPT-4o is most capable current model
- Consistent quality across all phases
- Simpler configuration and debugging

**Trade-off:** Higher cost than using GPT-4o-mini for execution, but ensures quality

### 2. Synchronous Task Execution
**Decision:** Execute tasks sequentially, not in parallel

**Rationale:**
- Simpler to implement and debug
- Easier to maintain context coherence
- Respects task dependencies naturally
- More transparent logging

**Trade-off:** Slower than parallel execution, but more predictable

### 3. Context Strategy: Recent Results + SQLite Storage
**Decision:** Keep last 5 results in context, store full results in SQLite

**Rationale:**
- Balances context awareness with token efficiency
- Synthesizer can access full results from database
- Simple to implement and reason about

**Trade-off:** Less sophisticated than compression-based approaches, but sufficient for research tasks

### 4. Tool Selection: Tavily over Raw Scraping
**Decision:** Use Tavily Search API instead of BeautifulSoup/Selenium

**Rationale:**
- Returns clean, AI-ready content
- Handles rate limiting and errors
- More reliable than scraping
- Faster development

**Trade-off:** External dependency and API costs, but worth it for quality

### 5. SQLite for State Persistence
**Decision:** SQLite for task state, not in-memory

**Rationale:**
- Enables session resume capability
- Easy to inspect and debug
- No external database setup
- ACID guarantees

**Trade-off:** Slight complexity overhead, but enables valuable features

## Project Structure

```
wolters_kluwer_case/
├── README.md                      # This file
├── IMPLEMENTATION_PLAN.md         # Detailed implementation plan
├── pyproject.toml                 # Project dependencies
├── .env.example                   # Environment template
├── main.py                        # CLI entry point
│
├── src/
│   ├── agent.py                   # Main agent controller
│   ├── planner.py                 # Goal → task plan
│   ├── executor.py                # Task execution
│   ├── synthesizer.py             # Result synthesis
│   ├── state.py                   # SQLite state management
│   ├── context.py                 # Context management
│   ├── models.py                  # Pydantic data models
│   ├── cli.py                     # Rich CLI interface
│   │
│   ├── tools/
│   │   ├── base.py                # Abstract tool interface
│   │   ├── registry.py            # Tool selection
│   │   └── web_search.py          # Tavily integration
│   │
│   └── prompts/
│       ├── planner.txt            # Planning instructions
│       └── synthesizer.txt        # Synthesis instructions
│
├── tests/
│   ├── test_models.py             # Data model tests
│   ├── test_state.py              # State management tests
│   ├── test_planner.py            # Planning tests
│   ├── test_tools.py              # Tool tests
│   └── test_agent.py              # Integration tests
│
├── examples/
│   └── transcript_*.md            # Example sessions
│
└── data/
    └── sessions.db                # SQLite database (gitignored)
```

## Time Spent

**Total Time:** ~5.5 hours

**Breakdown:**
- Stage 1 (Foundation): 1.25 hours - Data models, SQLite, CLI scaffold
- Stage 2 (Planning): 0.75 hours - Planner with OpenAI integration
- Stage 3 (Tools): 1.5 hours - Tool system and Tavily integration
- Stage 4 (Agent Loop): 1.25 hours - Executor, synthesizer, agent controller
- Stage 5 (Documentation): 0.75 hours - README, testing, cleanup

**Trade-offs Made:**
- Used GPT-4o instead of GPT-5.4 (not available) and GPT-4o-mini (for consistency)
- Implemented only Tavily search (required), skipped Firecrawl and document reader
- Sequential execution instead of parallel (simpler, more transparent)
- Basic context management (recent results) instead of advanced compression
- No web UI (CLI is faster to implement and sufficient for demo)

## Future Improvements

1. **Parallel Task Execution** - Execute independent tasks concurrently
2. **Advanced Context Compression** - Semantic compression for longer sessions
3. **Additional Tools** - Firecrawl scraper, document reader, code executor
4. **Web UI** - React/Streamlit interface for better UX
5. **RAG Integration** - Vector search over document collections
6. **Human-in-the-Loop** - User approval before executing tasks
7. **Streaming Responses** - Real-time output as tasks complete
8. **Cost Tracking** - Monitor API costs per session
9. **Session Resume** - Continue interrupted research sessions
10. **Multi-Agent Collaboration** - Specialized agents for different task types

## License

This project was created as a take-home case study for Wolters Kluwer.

## Contact

For questions or feedback about this implementation, please contact the repository owner.
