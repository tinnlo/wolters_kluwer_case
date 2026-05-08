"""Tests for the tool system."""

import pytest
from unittest.mock import Mock, patch, AsyncMock

from src.models import Task, ToolResult
from src.tools import Tool, ToolRegistry, WebSearchTool


class MockTool(Tool):
    """Mock tool for testing."""

    @property
    def name(self) -> str:
        return "mock_tool"

    @property
    def description(self) -> str:
        return "A mock tool for testing"

    def can_handle(self, task: Task) -> bool:
        return "mock" in task.description.lower()

    async def execute(self, task: Task, context: dict) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            task_id=task.id,
            success=True,
            summary="Mock execution",
            full_content="Mock content",
            metadata={},
        )


def test_tool_registry_register():
    """Test registering tools."""
    registry = ToolRegistry()
    tool = MockTool()

    registry.register(tool)

    assert registry.get_tool("mock_tool") == tool


def test_tool_registry_select_by_name():
    """Test selecting tool by name specified in task."""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    task = Task(
        id="task-1",
        description="Do something",
        tool_name="mock_tool",
        dependencies=[],
    )

    selected = registry.select_tool(task)
    assert selected == tool


def test_tool_registry_select_by_capability():
    """Test selecting tool by capability matching."""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    task = Task(
        id="task-1",
        description="Run mock test",
        dependencies=[],
    )

    selected = registry.select_tool(task)
    assert selected == tool


def test_web_search_tool_can_handle():
    """Test web search tool task detection."""
    tool = WebSearchTool(api_key="test-key")

    # WebSearchTool is a catch-all and handles all task types
    task1 = Task(id="t1", description="Search for Python tutorials", dependencies=[])
    assert tool.can_handle(task1)

    task2 = Task(id="t2", description="Find information about AI", dependencies=[])
    assert tool.can_handle(task2)

    task3 = Task(id="t3", description="Research WebAssembly adoption", dependencies=[])
    assert tool.can_handle(task3)

    # Also handles tasks that don't use search keywords (catalog, assess, synthesize, etc.)
    task4 = Task(id="t4", description="Catalog the main trading products", dependencies=[])
    assert tool.can_handle(task4)

    task5 = Task(id="t5", description="Calculate the sum", dependencies=[])
    assert tool.can_handle(task5)


def test_web_search_tool_extract_query():
    """Test query extraction from task description."""
    tool = WebSearchTool(api_key="test-key")

    # Test various formats
    assert tool._extract_query("Search for Python tutorials") == "python tutorials"
    assert tool._extract_query("Find information about AI") == "information about ai"
    assert tool._extract_query("WebAssembly adoption") == "webassembly adoption"

    # Queries longer than _MAX_QUERY_LEN must be truncated at a word boundary
    long_desc = "compare trading fees " + ("word " * 100)  # well over 400 chars
    result = tool._extract_query(long_desc)
    assert len(result) <= tool._MAX_QUERY_LEN
    assert not result.endswith(" ")  # no trailing space from word-boundary cut


@pytest.mark.asyncio
async def test_web_search_tool_execute_success():
    """Test successful web search execution."""
    mock_response_data = {
        "results": [
            {
                "title": "Test Result 1",
                "url": "https://example.com/1",
                "content": "Test content 1",
            },
            {
                "title": "Test Result 2",
                "url": "https://example.com/2",
                "content": "Test content 2",
            },
        ],
        "answer": "This is a test answer",
    }

    with patch("httpx.AsyncClient") as mock_client:
        # Setup mock
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = Mock()

        mock_post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = mock_post

        # Execute search
        tool = WebSearchTool(api_key="test-key")
        task = Task(id="task-1", description="Search for Python tutorials", dependencies=[])

        result = await tool.execute(task, {})

        # Verify result
        assert result.success is True
        assert result.tool_name == "web_search"
        assert result.task_id == "task-1"
        assert "2 results" in result.summary
        assert len(result.metadata["sources"]) == 2
        assert "Test Result 1" in result.full_content

        # Each source must be a dict with 'url' and 'title' keys so the
        # synthesizer can build a faithful titled reference list.
        for src in result.metadata["sources"]:
            assert isinstance(src, dict), "source must be a dict, not a plain URL string"
            assert "url" in src
            assert "title" in src
        assert result.metadata["sources"][0]["title"] == "Test Result 1"
        assert result.metadata["sources"][0]["url"] == "https://example.com/1"


@pytest.mark.asyncio
async def test_web_search_tool_execute_failure():
    """Test web search execution with API error."""
    with patch("httpx.AsyncClient") as mock_client:
        # Setup mock to raise error
        mock_post = AsyncMock(side_effect=Exception("API Error"))
        mock_client.return_value.__aenter__.return_value.post = mock_post

        # Execute search
        tool = WebSearchTool(api_key="test-key")
        task = Task(id="task-1", description="Search for Python tutorials", dependencies=[])

        result = await tool.execute(task, {})

        # Verify error handling
        assert result.success is False
        assert "error" in result.summary.lower()
        assert result.task_id == "task-1"
