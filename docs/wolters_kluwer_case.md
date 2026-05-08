# AI Engineering Take‑Home

![4daf8a55-3530-403b-a80e-0630a0c45861.png](https://img.notionusercontent.com/s3/prod-files-secure%2Fa3dcc302-40ae-4d39-bbef-d1ca7768c832%2Fa465183e-17de-4316-80dd-8402796b9be5%2F4daf8a55-3530-403b-a80e-0630a0c45861.png/size/w=1020?exp=1778313282&sig=GUil1prVTcAwPs7Fc1wztI6cgH4hhgpZsn-0OvrI3qE&id=2feeb482-52ec-80db-9e30-ec275e0a8f84&table=block&userId=02810845-8cea-4e53-bcb7-b40c6ce0a841&mtd=so)

_(Example inspiration: TODO/plan executors such as Cursor — plan → execute → log. You are free to design your own approach.)_

---

## The Challenge

**Build a small AI agent that helps users tackle complex goals by breaking them into actionable steps and executing them.**

Examples (not mandatory): research assistant, document helper, project planner, learning path generator, ops helper, etc.

**You decide:**

- What type of goals or domain to focus on
- How the AI interaction works (chat, CLI, minimal UI, etc.)
- How tasks are shown and updated
- What level of automation vs. user confirmation you provide

**Core concept:**

User describes a high‑level goal → AI structures it into a TODO plan → Agent executes tasks using tools → User receives results.

**Time frame:** ~4–6 hours recommended (flexible).

Please tell us how you spent your time and what trade‑offs you made.

> **Important:** Please do **not** use agent frameworks (LangChain, LangGraph, AutoGen, CrewAI, etc.). We want to see your own loop, prompts, and context handling.

---

## What We’re Looking For

This exercise tests your ability to **design and implement a practical AI system**, not just call an API.

### 1. Context & Prompt Engineering (35%)

- Clear prompt structure and instructions
- Thoughtful context selection (what to keep vs. drop)
- Basic handling of longer conversations or state
- Avoiding prompt bloat

### 2. Agent Loop & Tool Use (45%)

- High‑level goal → structured TODO list
- Simple execution loop (select task → execute → update status)
- Integration of **at least one real tool** (web search, document reading, API call, vector search, etc.)
- Transparent logging of what the agent is doing

### 3. Evaluation & Communication (20%)

- Clear explanation of how you would test or evaluate the system
- Ability to explain design and trade‑offs
- Clarity of README and demo

---

## Minimum Requirements

- **Planning:** Generate a structured plan from a user goal.
- **Execution Loop:** Iterate through tasks.
- **Tool Use:** Use at least one real external or local tool.
- **Context Strategy:** Briefly explain how you manage context and avoid prompt overflow.

Keep it simple — correctness and clarity matter more than features.

---

## Deliverables

1. **Source Code** – Public Git repository with clear structure and run instructions.
2. **README** – Briefly explain:
    - How the agent loop works
    - What tools you integrated
    - Your context strategy
    - 3–5 evaluation scenarios and what “success” means
3. **Example Transcript** – A real session from goal → plan → execution → result.
4. **Short Demo Video (3–5 min)** covering:
    - What your system can do
    - How information flows (context + tools)
    - How you would improve or extend it

---

## Optional Bonus

- Minimal UI or dashboard
- Persistence / resume capability
- RAG over a small document set
- Tracing or structured logs
- Basic guardrails or source attribution

---

## Important Notes

- **Keep the scope small and focused.**
- Narrow + polished beats ambitious + incomplete.
- You may mock or simplify components — just explain why.
- We care more about _how you think_ than how many features you build.

---

## Questions?

If anything is unclear, feel free to reach out during the application process.