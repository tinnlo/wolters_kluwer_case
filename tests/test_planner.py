"""Tests for the planning system."""

import json
import pytest
from unittest.mock import AsyncMock, Mock, patch

from src.planner import Planner
from src.models import ResearchPlan, Task


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response."""
    return {
        "tasks": [
            {
                "id": "task-1",
                "description": "Search for WebAssembly definition and capabilities",
                "dependencies": []
            },
            {
                "id": "task-2",
                "description": "Search for WebAssembly adoption statistics",
                "dependencies": ["task-1"]
            },
            {
                "id": "task-3",
                "description": "Search for WebAssembly use cases and examples",
                "dependencies": ["task-1"]
            }
        ]
    }


@pytest.mark.asyncio
async def test_planner_creates_valid_plan(mock_openai_response):
    """Test that planner creates a valid research plan."""
    with patch('src.planner.AsyncOpenAI') as mock_openai:
        # Setup mock
        mock_client = Mock()
        mock_openai.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(mock_openai_response)

        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Create planner and generate plan
        planner = Planner(api_key="test-key")
        plan = await planner.create_plan("Research WebAssembly adoption")

        # Verify plan structure
        assert isinstance(plan, ResearchPlan)
        assert plan.goal == "Research WebAssembly adoption"
        assert len(plan.tasks) == 3
        assert all(isinstance(task, Task) for task in plan.tasks)


def test_validate_dependencies_valid():
    """Test dependency validation with valid dependencies."""
    planner = Planner(api_key="test-key")

    tasks = [
        Task(id="task-1", description="Task 1", dependencies=[]),
        Task(id="task-2", description="Task 2", dependencies=["task-1"]),
        Task(id="task-3", description="Task 3", dependencies=["task-1", "task-2"]),
    ]

    # Should not raise
    planner._validate_dependencies(tasks)


def test_validate_dependencies_invalid():
    """Test dependency validation with invalid dependencies."""
    planner = Planner(api_key="test-key")

    tasks = [
        Task(id="task-1", description="Task 1", dependencies=[]),
        Task(id="task-2", description="Task 2", dependencies=["task-999"]),  # Invalid
    ]

    with pytest.raises(ValueError, match="invalid dependency"):
        planner._validate_dependencies(tasks)


def test_validate_dependencies_circular():
    """Test detection of circular dependencies."""
    planner = Planner(api_key="test-key")

    tasks = [
        Task(id="task-1", description="Task 1", dependencies=["task-2"]),
        Task(id="task-2", description="Task 2", dependencies=["task-1"]),
    ]

    with pytest.raises(ValueError, match="Circular dependency"):
        planner._validate_dependencies(tasks)


def test_validate_dependencies_self_reference():
    """Test detection of self-referencing dependencies."""
    planner = Planner(api_key="test-key")

    tasks = [
        Task(id="task-1", description="Task 1", dependencies=["task-1"]),
    ]

    with pytest.raises(ValueError, match="cannot depend on itself"):
        planner._validate_dependencies(tasks)


def test_validate_dependencies_duplicate_ids():
    """Test detection of duplicate task IDs."""
    planner = Planner(api_key="test-key")

    tasks = [
        Task(id="task-1", description="Task 1", dependencies=[]),
        Task(id="task-2", description="Task 2", dependencies=["task-1"]),
        Task(id="task-1", description="Duplicate Task 1", dependencies=[]),
    ]

    with pytest.raises(ValueError, match="Duplicate task IDs"):
        planner._validate_dependencies(tasks)
