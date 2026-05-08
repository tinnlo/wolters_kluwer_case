"""Data models for the research agent system."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SessionStatus(str, Enum):
    """Agent session lifecycle status."""

    PLANNING = "planning"
    EXECUTING = "executing"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    """A single research task within a plan."""

    id: str = Field(..., description="Unique task identifier")
    description: str = Field(..., description="What needs to be done")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current status")
    dependencies: list[str] = Field(
        default_factory=list, description="Task IDs that must complete first"
    )
    tool_name: str | None = Field(default=None, description="Tool to use for execution")
    result: str | None = Field(default=None, description="Task execution result summary")
    error: str | None = Field(default=None, description="Error message if failed")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResearchPlan(BaseModel):
    """A structured plan for accomplishing a research goal."""

    goal: str = Field(..., description="The high-level research objective")
    tasks: list[Task] = Field(..., description="Ordered list of tasks to execute")
    created_at: datetime = Field(default_factory=utc_now)


class ToolResult(BaseModel):
    """Result from a tool execution."""

    tool_name: str = Field(..., description="Name of the tool that was executed")
    task_id: str = Field(..., description="ID of the task this result belongs to")
    success: bool = Field(..., description="Whether the tool execution succeeded")
    summary: str = Field(..., description="Brief summary of the result")
    full_content: str = Field(..., description="Complete tool output")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata (sources, URLs, etc.)"
    )
    created_at: datetime = Field(default_factory=utc_now)


class AgentSession(BaseModel):
    """A complete agent execution session."""

    session_id: str = Field(..., description="Unique session identifier")
    goal: str = Field(..., description="The research goal")
    plan: ResearchPlan | None = Field(default=None, description="The generated plan")
    final_report: str | None = Field(default=None, description="Synthesized final output")
    status: SessionStatus = Field(default=SessionStatus.PLANNING, description="Current session phase")
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class LogEntry(BaseModel):
    """A log entry for transparent tracking."""

    session_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    level: Literal["INFO", "WARNING", "ERROR"] = Field(..., description="Log level")
    component: str = Field(..., description="Which component generated this log")
    message: str = Field(..., description="Log message")
    metadata: dict[str, Any] = Field(default_factory=dict)
