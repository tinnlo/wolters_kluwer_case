# AI Agent System - Implementation Plan

## Context

This is a take-home case study for an AI Engineering position at Wolters Kluwer. The challenge is to build a small AI agent that helps users tackle complex goals by breaking them into actionable steps and executing them.

**Problem Statement:**
Users have complex goals that require multiple steps to accomplish. They need an AI system that can:
- Understand high-level goals
- Break them down into structured, actionable tasks
- Execute those tasks using real tools
- Provide transparent logging of the process
- Synthesize results into useful outputs

**Key Constraints:**
- Time frame: 4-6 hours recommended
- NO agent frameworks (LangChain, LangGraph, AutoGen, CrewAI, etc.)
- Must implement custom agent loop, prompts, and context handling
- Must integrate at least one real external or local tool

**Evaluation Criteria:**
- Context & Prompt Engineering (35%)
- Agent Loop & Tool Use (45%)
- Evaluation & Communication (20%)

**Architecture Reference:**
The provided diagram shows the intended flow:
```
User Input → Planning Agent → TODO List → Execution Agent (with Tools) → Logs → User Output
```

---

## Technology Stack

### Core Technologies

**Language:** Python 3.11+
- Rich ecosystem for AI/LLM work
- Excellent async support for API calls
- Strong typing with type hints
- Fast prototyping capabilities

**LLM Provider:** OpenAI API
- **gpt-5.4** for planning and synthesis (most capable)
- **gpt-5-mini** for task execution and tool selection (cost-effective)
- Structured outputs support for reliable JSON parsing
- Function calling for tool integration

**Tools:**
- **Tavily Search API** - AI-optimized web search for research tasks
- **File Operations** - Read/write local documents
- **Code Execution** (optional) - Safe Python code execution for calculations

**State Management:** SQLite
- Lightweight, no external database required
- ACID compliance for reliability
- Easy to inspect and debug
- Enables session persistence and resume capability

**Supporting Libraries:**
- `openai` - Official OpenAI Python SDK
- `pydantic` - Data validation and structured outputs
- `rich` - Beautiful CLI output and progress tracking
- `python-dotenv` - Environment configuration
- `httpx` - Async HTTP client for tool calls
- `pytest` - Testing framework

---

## Domain Focus: Research Assistant

**Why Research Assistant?**
- Clear success criteria (relevant information found and synthesized)
- Natural fit for web search tool integration
- Demonstrates planning, execution, and synthesis capabilities
- Realistic scope for 4-6 hour timeline
- Easy to evaluate quality of results

**Use Cases:**
- "Research the current state of WebAssembly adoption"
- "Compare GraphQL vs REST APIs for mobile applications"
- "Investigate security best practices for LLM applications"

---

## System Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI Interface                        │
│                    (User Interaction Layer)                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      Agent Controller                        │
│              (Main orchestration and loop logic)             │
└─────────────────────────────────────────────────────────────┘
         ↓                    ↓                    ↓
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Planner    │    │   Executor   │    │   Context    │
│  (gpt-5.4)   │    │ (gpt-5-mini) │    │   Manager    │
└──────────────┘    └──────────────┘    └──────────────┘
                            ↓
                    ┌──────────────┐
                    │ Tool Registry│
                    └──────────────┘
                            ↓
        ┌───────────────────┼───────────────────┐
        ↓                   ↓                   ↓
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Web Search  │    │Document Reader│   │ Synthesizer  │
│   (Tavily)   │    │ (File I/O)   │    │  (gpt-5.4)   │
└──────────────┘    └──────────────┘    └──────────────┘
                            ↓
                    ┌──────────────┐
                    │State Manager │
                    │   (SQLite)   │
                    └──────────────┘
```

### Data Flow

**Phase 1: Planning**
1. User provides high-level goal via CLI
2. Agent Controller invokes Planner with goal
3. Planner (gpt-5.4) generates structured TODO list with dependencies
4. State Manager persists tasks to SQLite
5. CLI displays plan to user for confirmation

**Phase 2: Execution**
1. Agent Controller enters execution loop
2. For each pending task (respecting dependencies):
   - Executor (gpt-5-mini) determines required tool(s)
   - Tool Registry dispatches to appropriate tool
   - Tool executes and returns results
   - State Manager updates task status and stores results
   - Context Manager tracks conversation history
   - CLI displays progress and logs
3. Loop continues until all tasks complete or error

**Phase 3: Synthesis**
1. Agent Controller invokes Synthesizer with all task results
2. Synthesizer (gpt-5.4) creates coherent final report
3. State Manager saves final output
4. CLI displays results to user

---

## Context Management Strategy

### The Challenge
- Research tasks accumulate context: goal + plan + tool results + synthesis
- OpenAI models have token limits (128K for gpt-5.4, 128K for gpt-5-mini)
- Need to maintain coherence while controlling costs
- Long sessions can overflow context window

### Solution: Tiered Context Retention

**Tier 1: Always Keep (Core Context)**
- System instructions and role definition
- Original user goal
- Complete task plan structure (task IDs, descriptions, dependencies)
- Current task being executed

**Tier 2: Recent Context (Last 5 Tasks)**
- Latest tool results (full detail)
- Recent task completions
- User feedback or corrections
- Error messages and recovery attempts

**Tier 3: Summarized Context (Older Tasks)**
- Compress after 10 tasks
- Keep: task ID, status, key findings (2-3 sentences)
- Drop: raw search results, verbose tool outputs, intermediate reasoning

**Tier 4: Dropped Context**
- Raw HTML/web content after extraction
- Redundant confirmations
- Detailed API responses after parsing

### Implementation Details

**Token Budget Monitoring:**
- Track tokens per API call using OpenAI's usage data
- Set warning threshold at 100K tokens
- Trigger compression at 110K tokens
- Hard limit at 120K tokens (leave buffer)

**Compression Strategy:**
```python
def compress_context(history):
    # Keep system prompt and goal (Tier 1)
    core = history[:2]
    
    # Keep last 5 interactions (Tier 2)
    recent = history[-10:]
    
    # Summarize middle section (Tier 3)
    middle = history[2:-10]
    summarized = summarize_with_llm(middle)
    
    return core + [summarized] + recent
```

**Structured State Separation:**
- Store full tool results in SQLite (not in LLM context)
- Only include summaries in prompts
- LLM can request full details by task ID if needed
- Reduces prompt bloat by 60-70%

---

## Implementation Stages

### Stage 1: Foundation & Data Models
**Goal:** Set up project structure and core data models  
**Time Estimate:** 1.5 hours

**Tasks:**
1. Initialize Python project with `pyproject.toml` and dependencies
2. Set up virtual environment and install packages
3. Create `.env.example` with API key placeholders
4. Define Pydantic models for Task, ResearchPlan, AgentSession
5. Implement SQLite schema and State Manager with CRUD operations
6. Create basic CLI scaffold with Rich console
7. Add logging configuration

**Success Criteria:**
- ✅ Can create and persist task plans to SQLite
- ✅ Can query task state correctly (pending, in_progress, completed)
- ✅ CLI accepts input and displays formatted output
- ✅ All models have proper type hints and validation

**Critical Files:**
- `src/models.py` - Pydantic data models
- `src/state.py` - SQLite state management
- `src/cli.py` - Command-line interface
- `pyproject.toml` - Dependencies

**Tests:**
- Create a task plan and verify SQLite persistence
- Query tasks by status
- Update task status and verify changes

---

### Stage 2: Planning System
**Goal:** Convert user goals into structured task plans  
**Time Estimate:** 1 hour

**Tasks:**
1. Design planning prompt with clear instructions and examples
2. Implement Planner class with OpenAI API integration (gpt-5.4)
3. Use structured outputs to ensure valid JSON task lists
4. Add task dependency validation logic
5. Implement plan review and user confirmation flow
6. Add error handling for malformed plans

**Success Criteria:**
- ✅ Given "Research the impact of AI on healthcare", produces 5-7 specific, actionable tasks
- ✅ Tasks have clear descriptions and realistic dependencies
- ✅ Output is valid JSON matching Task schema
- ✅ Handles edge cases (vague goals, overly broad topics)

**Critical Files:**
- `src/planner.py` - Planning logic
- `src/prompts/planner.txt` - Planning prompt template

**Planning Prompt Structure:**
```
System: You are a research planning assistant...
- Break down goals into 5-7 specific, actionable tasks
- Each task should be completable with available tools
- Specify dependencies between tasks
- Output valid JSON matching schema

User: [goal]
```

**Tests:**
- Test with broad goal: "Research WebAssembly adoption"
- Test with comparative goal: "Compare GraphQL vs REST"
- Test with vague goal: "Learn about AI" (should ask for clarification)

---

### Stage 3: Tool System
**Goal:** Implement real tools for task execution  
**Time Estimate:** 1.5 hours

**Tasks:**
1. Create abstract Tool base class with execute() interface
2. Implement Tool Registry with registration and selection logic
3. Build Web Search tool with Tavily API integration
4. Build Document Reader tool for local file operations
5. Build Synthesizer tool using gpt-5.4 for combining results
6. Add error handling, retries, and rate limiting
7. Implement tool result formatting and storage

**Success Criteria:**
- ✅ Web search returns relevant, recent results for technical queries
- ✅ Document reader extracts content from markdown/text files
- ✅ Synthesizer combines multiple sources into coherent summary
- ✅ Tools handle errors gracefully (API failures, rate limits, invalid inputs)
- ✅ Tool results are properly formatted and stored in SQLite

**Critical Files:**
- `src/tools/base.py` - Abstract Tool interface
- `src/tools/registry.py` - Tool registration and selection
- `src/tools/web_search.py` - Tavily integration
- `src/tools/document_reader.py` - File I/O operations
- `src/tools/synthesizer.py` - LLM-based synthesis

**Tool Interface:**
```python
class Tool(ABC):
    @abstractmethod
    async def execute(self, task: Task, context: dict) -> ToolResult:
        pass
    
    @abstractmethod
    def can_handle(self, task: Task) -> bool:
        pass
```

**Tests:**
- Search for "Python async best practices" and verify results
- Read a local markdown file and extract content
- Synthesize 3 search results into a coherent paragraph
- Test error handling with invalid API key
- Test rate limiting with rapid successive calls

---

### Stage 4: Agent Loop & Execution
**Goal:** Orchestrate planning, execution, and synthesis  
**Time Estimate:** 1 hour

**Tasks:**
1. Implement main Agent Controller with run_agent_loop()
2. Build Executor class with tool dispatch logic (gpt-5-mini)
3. Implement task selection with dependency resolution
4. Add Context Manager with token tracking and compression
5. Integrate all components into end-to-end flow
6. Add progress tracking and logging with Rich
7. Implement error recovery and retry logic

**Success Criteria:**
- ✅ Complete research task: "Compare Python vs Rust for web development"
- ✅ Executes 5-6 tasks in correct dependency order
- ✅ Produces final synthesized report with citations
- ✅ Handles tool failures gracefully (retries, fallbacks)
- ✅ Context stays under token limits for 10+ task sessions
- ✅ Progress is visible in CLI with clear logging

**Critical Files:**
- `src/agent.py` - Main agent controller and loop
- `src/executor.py` - Task execution engine
- `src/context.py` - Context window management

**Agent Loop Pseudocode:**
```python
async def run_agent_loop(goal: str):
    # Phase 1: Planning
    plan = await planner.create_plan(goal)
    state.save_plan(plan)
    
    # Phase 2: Execution
    while state.has_pending_tasks():
        task = state.get_next_task()  # Respects dependencies
        
        tool = registry.select_tool(task)
        result = await tool.execute(task)
        
        state.update_task(task.id, status="completed", result=result)
        context.add_interaction(task, result)
        
        if context.should_compress():
            context.compress()
    
    # Phase 3: Synthesis
    final_report = await synthesizer.synthesize(state.get_all_results())
    return final_report
```

**Tests:**
- End-to-end test with complete research goal
- Test dependency resolution (task B waits for task A)
- Test context compression after 10 tasks
- Test error recovery when tool fails
- Test session persistence and resume

---

### Stage 5: Evaluation & Documentation
**Goal:** Testing, documentation, and demo preparation  
**Time Estimate:** 1 hour

**Tasks:**
1. Define 5 evaluation scenarios with success criteria
2. Run all scenarios and capture transcripts
3. Document results, limitations, and edge cases
4. Write comprehensive README with:
   - Architecture explanation
   - Setup instructions
   - Context management strategy
   - Tool descriptions
   - Evaluation results
5. Create EVALUATION.md with detailed test cases
6. Record 3-5 minute demo video showing:
   - Complete flow from goal to result
   - How information flows through components
   - Context management in action
   - Future improvements
7. Code cleanup: docstrings, type hints, formatting
8. Final testing and bug fixes

**Success Criteria:**
- ✅ All 5 evaluation scenarios documented with results
- ✅ README is clear, complete, and easy to follow
- ✅ Demo video covers all required topics
- ✅ Code passes type checking (mypy) and linting (ruff)
- ✅ All tests pass
- ✅ Repository is ready for submission

**Critical Files:**
- `README.md` - Main documentation
- `EVALUATION.md` - Test scenarios and results
- `examples/transcript_*.md` - Example sessions
- `examples/demo_video.mp4` - Screen recording

---

## Evaluation Scenarios

### Scenario 1: Broad Technical Topic
**Goal:** "Research the current state of WebAssembly adoption"

**Expected Behavior:**
- Planner creates 5-7 tasks covering: definition, use cases, adoption metrics, major implementations, future trends
- Web search finds recent articles (2025-2026)
- Synthesizer creates coherent report with citations

**Success Metrics:**
- ✅ 100% task completion rate
- ✅ 4/5 relevance score (manual evaluation)
- ✅ Context usage < 50K tokens
- ✅ Execution time < 3 minutes
- ✅ All sources from 2024-2026

---

### Scenario 2: Comparative Analysis
**Goal:** "Compare GraphQL vs REST APIs for mobile applications"

**Expected Behavior:**
- Planner identifies key comparison dimensions: performance, developer experience, ecosystem, use cases
- Tasks cover both technologies fairly
- Synthesizer provides balanced comparison with pros/cons

**Success Metrics:**
- ✅ 100% task completion rate
- ✅ Covers at least 4 comparison dimensions
- ✅ Balanced coverage (not biased toward one technology)
- ✅ Context usage < 60K tokens
- ✅ Execution time < 4 minutes

---

### Scenario 3: Emerging Technology
**Goal:** "Investigate recent developments in AI code generation tools"

**Expected Behavior:**
- Planner creates tasks for: current landscape, recent releases, capabilities, limitations, trends
- Web search finds very recent information (2025-2026)
- Synthesizer highlights what's new and emerging

**Success Metrics:**
- ✅ 100% task completion rate
- ✅ All sources from 2025-2026 (no outdated info)
- ✅ Mentions at least 5 different tools
- ✅ Context usage < 55K tokens
- ✅ Execution time < 3 minutes

---

### Scenario 4: Error Recovery
**Goal:** "Research [intentionally obscure topic with limited results]"

**Expected Behavior:**
- Planner creates reasonable tasks despite limited information
- Web search returns few or no results
- Agent handles gracefully: tries alternative queries, reports limitations honestly
- No hallucination of fake information

**Success Metrics:**
- ✅ Graceful degradation (doesn't crash)
- ✅ Clear error messages about limited information
- ✅ No hallucinated facts (manual verification)
- ✅ Suggests alternative approaches or related topics
- ✅ Execution time < 2 minutes

---

### Scenario 5: Complex Multi-Step Research
**Goal:** "Research security implications of using LLMs in production and mitigation best practices"

**Expected Behavior:**
- Planner creates 8-10 tasks covering: threat landscape, specific vulnerabilities, mitigation strategies, tools, case studies
- Tasks have logical dependencies (understand threats before mitigations)
- Synthesizer maintains coherence across many tasks
- Context management handles longer session

**Success Metrics:**
- ✅ 100% task completion rate
- ✅ Logical task ordering respected
- ✅ No information loss from context compression
- ✅ 4/5 synthesis quality score
- ✅ Context usage < 80K tokens
- ✅ Execution time < 5 minutes

---

## File Structure

```
wolters_kluwer_case/
├── README.md                      # Main documentation
├── IMPLEMENTATION_PLAN.md         # This file
├── EVALUATION.md                  # Test scenarios and results
├── pyproject.toml                 # Project dependencies
├── .env.example                   # Environment template
├── .gitignore
│
├── src/
│   ├── __init__.py
│   ├── agent.py                   # Main agent controller
│   ├── planner.py                 # Goal → task plan (gpt-5.4)
│   ├── executor.py                # Task execution (gpt-5-mini)
│   ├── state.py                   # SQLite state management
│   ├── context.py                 # Context window management
│   ├── models.py                  # Pydantic data models
│   ├── cli.py                     # Command-line interface
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                # Abstract tool interface
│   │   ├── registry.py            # Tool discovery and selection
│   │   ├── web_search.py          # Tavily integration
│   │   ├── document_reader.py     # File I/O operations
│   │   └── synthesizer.py         # LLM-based synthesis (gpt-5.4)
│   │
│   └── prompts/
│       ├── system.txt             # Base system prompt
│       ├── planner.txt            # Planning instructions
│       ├── executor.txt           # Execution instructions
│       └── synthesizer.txt        # Synthesis instructions
│
├── tests/
│   ├── __init__.py
│   ├── test_models.py             # Data model tests
│   ├── test_state.py              # State management tests
│   ├── test_planner.py            # Planning tests
│   ├── test_tools.py              # Tool tests
│   └── test_agent.py              # Integration tests
│
├── examples/
│   ├── transcript_scenario1.md    # Example session 1
│   ├── transcript_scenario2.md    # Example session 2
│   ├── transcript_scenario5.md    # Complex example
│   └── demo_video.mp4             # Screen recording
│
├── data/
│   └── sessions.db                # SQLite database (gitignored)
│
└── docs/
    └── wolters_kluwer_case.md     # Original requirements
```

---

## Key Design Decisions & Trade-offs

### 1. OpenAI API with Model Splitting
**Decision:** Use gpt-5.4 for planning/synthesis, gpt-5-mini for execution

**Rationale:**
- Planning requires strong reasoning → gpt-5.4
- Task execution is more straightforward → gpt-5-mini saves cost
- Synthesis needs coherence → gpt-5.4
- Estimated cost savings: 60-70% vs using gpt-5.4 for everything

**Trade-off:** Slightly more complex code (two model configurations), but significant cost savings and appropriate capability matching

---

### 2. Domain: Research Assistant
**Decision:** Focus on technical research tasks

**Rationale:**
- Clear success criteria (relevant information found)
- Natural fit for web search tool
- Demonstrates all required capabilities
- Realistic scope for timeline
- Easy to evaluate objectively

**Trade-off:** Less novel than some domains, but execution quality matters more than novelty for this evaluation

---

### 3. Synchronous Task Execution
**Decision:** Execute tasks sequentially, not in parallel

**Rationale:**
- Simpler to implement and debug
- Easier to maintain context coherence
- Respects task dependencies naturally
- More transparent logging
- Can add parallelization later if needed

**Trade-off:** Slower than parallel execution, but more predictable and easier to understand

---

### 4. Context Strategy: Tiered Retention + Structured State
**Decision:** Hybrid approach with tiered context and SQLite storage

**Rationale:**
- Tiered retention keeps important context while dropping noise
- SQLite stores full results outside LLM context
- Compression triggers at 110K tokens (safe buffer)
- Enables long sessions without overflow

**Trade-off:** More complex than naive approach, but necessary for real-world use and demonstrates strong context management skills

---

### 5. Tool Selection: Tavily over Raw Scraping
**Decision:** Use Tavily Search API instead of BeautifulSoup/Selenium

**Rationale:**
- Returns clean, AI-ready content
- Handles rate limiting and errors
- More reliable than scraping
- Faster development
- Better results for research tasks

**Trade-off:** External dependency and API costs, but worth it for quality and development speed

---

### 6. State Persistence: SQLite
**Decision:** SQLite for task state, not in-memory

**Rationale:**
- Enables resume capability (bonus feature)
- Easy to inspect and debug
- No external database setup
- ACID guarantees
- Demonstrates production-ready thinking

**Trade-off:** Slight complexity overhead, but enables valuable features

---

### 7. CLI with Rich
**Decision:** Terminal-based interface with rich formatting

**Rationale:**
- Fastest to implement (fits timeline)
- Excellent UX with colors, progress bars, tables
- Great for demos and screenshots
- Professional appearance
- No frontend complexity

**Trade-off:** Not as polished as web UI, but sufficient for evaluation and actually preferred by many developers

---

### 8. Error Handling: Fail-Soft with Logging
**Decision:** Log errors, mark tasks as failed, continue with other tasks

**Rationale:**
- Partial results better than complete failure
- Transparent about limitations
- Demonstrates robustness
- Real-world systems need graceful degradation

**Trade-off:** May produce incomplete reports, but honest about capabilities

---

## Risk Mitigation

### Technical Risks

**API Rate Limits**
- Mitigation: Exponential backoff with retries
- Mitigation: Rate limiting in tool layer
- Mitigation: Graceful degradation if limits hit

**Context Overflow**
- Mitigation: Aggressive compression at 110K tokens
- Mitigation: Monitor token usage per request
- Mitigation: Structured state in SQLite (not in context)

**Tool Failures**
- Mitigation: Try-catch with specific error handling
- Mitigation: Retry logic with exponential backoff
- Mitigation: Fallback strategies (alternative queries)
- Mitigation: Clear error messages to user

**Malformed LLM Outputs**
- Mitigation: Use OpenAI structured outputs for JSON
- Mitigation: Pydantic validation on all data models
- Mitigation: Fallback parsing strategies
- Mitigation: Clear error messages and retry

### Scope Risks

**Feature Creep**
- Mitigation: Stick to minimum requirements first
- Mitigation: Mark bonus features clearly
- Mitigation: Time-box each stage

**Over-Engineering**
- Mitigation: Simple solutions first
- Mitigation: Refactor only if needed
- Mitigation: Focus on working code over perfect code

**Time Overrun**
- Mitigation: Prioritize core loop over polish
- Mitigation: Cut bonus features if needed
- Mitigation: 30-minute buffer in timeline

---

## Timeline & Milestones

**Total Time Budget: 6 hours**

| Stage | Duration | Cumulative | Key Deliverable |
|-------|----------|------------|-----------------|
| Stage 1: Foundation | 1.5 hours | 1.5h | Working data models and state management |
| Stage 2: Planning | 1.0 hour | 2.5h | Goal → structured task plan |
| Stage 3: Tools | 1.5 hours | 4.0h | Web search, file reader, synthesizer |
| Stage 4: Agent Loop | 1.0 hour | 5.0h | End-to-end execution |
| Stage 5: Evaluation | 1.0 hour | 6.0h | Documentation, tests, demo |
| **Buffer** | 0.5 hours | 6.5h | Unexpected issues |

**Checkpoints:**
- ✅ After Stage 1: Can persist and query tasks
- ✅ After Stage 2: Can generate valid plans
- ✅ After Stage 3: Tools return real results
- ✅ After Stage 4: Complete end-to-end flow works
- ✅ After Stage 5: Ready for submission

---

## Verification Strategy

### Unit Tests
- Data model validation (Pydantic)
- State management CRUD operations
- Tool execution with mocked APIs
- Context compression logic

### Integration Tests
- End-to-end agent loop
- Planning → execution → synthesis flow
- Error recovery scenarios
- Context management under load

### Manual Testing
- Run all 5 evaluation scenarios
- Verify output quality manually
- Check for hallucinations
- Test edge cases (vague goals, errors, etc.)

### Code Quality
- Type checking with mypy
- Linting with ruff
- Format with black
- Docstrings for all public functions

---

## Future Improvements (Out of Scope)

These are explicitly out of scope for the 4-6 hour timeline but worth mentioning:

1. **Parallel Task Execution** - Execute independent tasks concurrently
2. **Web UI** - React/Streamlit interface for better UX
3. **RAG Integration** - Vector search over document collections
4. **Multi-Agent Collaboration** - Specialized agents for different task types
5. **Human-in-the-Loop** - User approval before executing tasks
6. **Advanced Tool Integration** - Code execution, database queries, API calls
7. **Streaming Responses** - Real-time output as tasks complete
8. **Cost Tracking** - Monitor API costs per session
9. **A/B Testing** - Compare different planning strategies
10. **Production Deployment** - Docker, API server, authentication

---

## Success Criteria Summary

**Minimum Requirements (Must Have):**
- ✅ Planning: Generate structured plan from user goal
- ✅ Execution Loop: Iterate through tasks with dependency resolution
- ✅ Tool Use: At least one real external tool (Tavily web search)
- ✅ Context Strategy: Documented and implemented tiered retention

**Evaluation Criteria (Must Demonstrate):**
- ✅ Context & Prompt Engineering (35%): Clear prompts, context management, structured outputs
- ✅ Agent Loop & Tool Use (45%): Working loop, tool integration, transparent logging
- ✅ Evaluation & Communication (20%): 5 scenarios, clear README, demo video

**Deliverables (Must Submit):**
- ✅ Source code in public Git repository
- ✅ README with architecture, tools, context strategy, evaluation
- ✅ Example transcripts (at least 3)
- ✅ Demo video (3-5 minutes)

**Bonus Features (Nice to Have):**
- ✅ Session persistence and resume capability (SQLite)
- ✅ Rich CLI with progress tracking
- ✅ Structured logging
- ⬜ Minimal UI (out of scope for timeline)
- ⬜ RAG over documents (out of scope for timeline)

---

## Notes

**Time Spent:** This plan took approximately 30 minutes to create

**Trade-offs Made:**
- Chose research assistant over more novel domains (faster to implement, clearer evaluation)
- Sequential execution over parallel (simpler, more transparent)
- CLI over web UI (faster development, still professional)
- Tavily over raw scraping (better results, faster development)

**Key Insights:**
- The 45% weight on agent loop & tool use suggests this is the most important area
- Context management (35%) is critical - need to demonstrate thoughtful approach
- Evaluation (20%) requires clear scenarios and honest assessment
- No frameworks means showing understanding of fundamentals

**Questions for Clarification:**
- None at this time - requirements are clear

**Ready to Implement:** Yes, this plan provides clear stages, success criteria, and verification steps for each component.