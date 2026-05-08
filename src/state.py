"""SQLite-based state management for agent sessions."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from .models import AgentSession, LogEntry, ResearchPlan, Task, TaskStatus, ToolResult


class StateManager:
    """Manages persistent state in SQLite."""

    def __init__(self, db_path: str = "data/sessions.db"):
        """Initialize state manager with database path."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    plan_json TEXT,
                    final_report TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    tool_name TEXT,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, id),
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    full_content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks (id),
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    component TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
                )
            """)

            conn.commit()

    def create_session(self, session: AgentSession) -> None:
        """Create a new session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, goal, plan_json, final_report, status,
                                     created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.goal,
                    session.plan.model_dump_json() if session.plan else None,
                    session.final_report,
                    session.status,
                    session.created_at.isoformat(),
                    session.completed_at.isoformat() if session.completed_at else None,
                ),
            )
            conn.commit()

    def update_session(
        self,
        session_id: str,
        plan: Optional[ResearchPlan] = None,
        final_report: Optional[str] = None,
        status: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        """Update session fields."""
        updates = []
        params = []

        if plan is not None:
            updates.append("plan_json = ?")
            params.append(plan.model_dump_json())

        if final_report is not None:
            updates.append("final_report = ?")
            params.append(final_report)

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if completed_at is not None:
            updates.append("completed_at = ?")
            params.append(completed_at.isoformat())

        if not updates:
            return

        params.append(session_id)
        query = f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = ?"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(query, params)
            conn.commit()

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Retrieve a session by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return AgentSession(
                session_id=row["session_id"],
                goal=row["goal"],
                plan=ResearchPlan.model_validate_json(row["plan_json"])
                if row["plan_json"]
                else None,
                final_report=row["final_report"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None,
            )

    def save_task(self, session_id: str, task: Task) -> None:
        """Save or update a task."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks
                (id, session_id, description, status, dependencies_json, tool_name,
                 result, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    session_id,
                    task.description,
                    task.status.value,
                    json.dumps(task.dependencies),
                    task.tool_name,
                    task.result,
                    task.error,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get_task(self, session_id: str, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? AND id = ?",
                (session_id, task_id),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return Task(
                id=row["id"],
                description=row["description"],
                status=TaskStatus(row["status"]),
                dependencies=json.loads(row["dependencies_json"]),
                tool_name=row["tool_name"],
                result=row["result"],
                error=row["error"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def get_session_tasks(self, session_id: str) -> list[Task]:
        """Get all tasks for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )

            tasks = []
            for row in cursor.fetchall():
                tasks.append(
                    Task(
                        id=row["id"],
                        description=row["description"],
                        status=TaskStatus(row["status"]),
                        dependencies=json.loads(row["dependencies_json"]),
                        tool_name=row["tool_name"],
                        result=row["result"],
                        error=row["error"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                    )
                )

            return tasks

    def update_task_status(
        self,
        session_id: str,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update task status and result."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, result = ?, error = ?, updated_at = ?
                WHERE session_id = ? AND id = ?
                """,
                (
                    status.value,
                    result,
                    error,
                    datetime.now(UTC).isoformat(),
                    session_id,
                    task_id,
                ),
            )
            conn.commit()

    def save_tool_result(self, session_id: str, tool_result: ToolResult) -> None:
        """Save a tool execution result."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tool_results
                (tool_name, task_id, session_id, success, summary, full_content,
                 metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_result.tool_name,
                    tool_result.task_id,
                    session_id,
                    1 if tool_result.success else 0,
                    tool_result.summary,
                    tool_result.full_content,
                    json.dumps(tool_result.metadata),
                    tool_result.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get_tool_results(self, session_id: str) -> list[ToolResult]:
        """Get all tool results for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tool_results WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )

            results = []
            for row in cursor.fetchall():
                results.append(
                    ToolResult(
                        tool_name=row["tool_name"],
                        task_id=row["task_id"],
                        success=bool(row["success"]),
                        summary=row["summary"],
                        full_content=row["full_content"],
                        metadata=json.loads(row["metadata_json"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                )

            return results

    def add_log(self, log_entry: LogEntry) -> None:
        """Add a log entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO logs (session_id, timestamp, level, component, message, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    log_entry.session_id,
                    log_entry.timestamp.isoformat(),
                    log_entry.level,
                    log_entry.component,
                    log_entry.message,
                    json.dumps(log_entry.metadata),
                ),
            )
            conn.commit()

    def get_logs(self, session_id: str) -> list[LogEntry]:
        """Get all logs for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM logs WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            )

            logs = []
            for row in cursor.fetchall():
                logs.append(
                    LogEntry(
                        session_id=row["session_id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        level=row["level"],
                        component=row["component"],
                        message=row["message"],
                        metadata=json.loads(row["metadata_json"]),
                    )
                )

            return logs

    def has_pending_tasks(self, session_id: str) -> bool:
        """Check if session has any pending tasks."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM tasks
                WHERE session_id = ? AND status IN (?, ?)
                """,
                (session_id, TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value),
            )
            count = cursor.fetchone()[0]
            return count > 0

    def get_next_task(self, session_id: str) -> Optional[Task]:
        """Get the next pending task that has all dependencies completed."""
        tasks = self.get_session_tasks(session_id)

        # Build a map of task statuses
        task_status_map = {task.id: task.status for task in tasks}

        # Find first pending task with all dependencies completed
        for task in tasks:
            if task.status != TaskStatus.PENDING:
                continue

            # Check if all dependencies are completed
            dependencies_met = all(
                task_status_map.get(dep_id) == TaskStatus.COMPLETED
                for dep_id in task.dependencies
            )

            if dependencies_met:
                return task

        return None
