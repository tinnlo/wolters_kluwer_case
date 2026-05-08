"""Planning system that converts goals into structured task plans."""

import json
import os
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from .models import ResearchPlan, Task


class Planner:
    """Converts high-level research goals into structured task plans."""

    def __init__(self, api_key: str | None = None):
        """Initialize planner with OpenAI client."""
        self.client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.1")

        # Load planning prompt
        prompt_path = os.path.join(
            os.path.dirname(__file__), "prompts", "planner.txt"
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    async def create_plan(self, goal: str) -> ResearchPlan:
        """Create a structured research plan from a goal.

        Args:
            goal: The high-level research objective

        Returns:
            ResearchPlan with structured tasks

        Raises:
            ValueError: If plan generation fails or produces invalid output
        """
        try:
            # Define the JSON schema for structured output
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "research_plan",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "description": {"type": "string"},
                                        "dependencies": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["id", "description", "dependencies"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["tasks"],
                        "additionalProperties": False,
                    },
                },
            }

            # Call OpenAI API with structured output
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": f"Create a research plan for this goal: {goal}",
                    },
                ],
                response_format=response_format,
                temperature=0.7,
            )

            # Parse response
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from OpenAI")

            plan_data = json.loads(content)

            # Validate and create Task objects
            tasks = []
            for task_data in plan_data["tasks"]:
                task = Task(
                    id=task_data["id"],
                    description=task_data["description"],
                    dependencies=task_data["dependencies"],
                )
                tasks.append(task)

            if not tasks:
                raise ValueError(
                    "Planner returned an empty task list. "
                    "The goal may be too vague — try rephrasing it."
                )

            # Validate dependencies
            self._validate_dependencies(tasks)

            # Create and return ResearchPlan
            return ResearchPlan(goal=goal, tasks=tasks)

        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse plan JSON: {e}")
        except ValidationError as e:
            raise ValueError(f"Invalid plan structure: {e}")
        except Exception as e:
            raise ValueError(f"Failed to create plan: {e}")

    def _validate_dependencies(self, tasks: list[Task]) -> None:
        """Validate that task dependencies are valid.

        Args:
            tasks: List of tasks to validate

        Raises:
            ValueError: If dependencies are invalid
        """
        task_ids = [task.id for task in tasks]

        # Check for duplicate task IDs
        if len(task_ids) != len(set(task_ids)):
            duplicates = [tid for tid in task_ids if task_ids.count(tid) > 1]
            raise ValueError(f"Duplicate task IDs found: {set(duplicates)}")

        task_ids = set(task_ids)

        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    raise ValueError(
                        f"Task {task.id} has invalid dependency: {dep_id}"
                    )

                # Check for self-dependency
                if dep_id == task.id:
                    raise ValueError(f"Task {task.id} cannot depend on itself")

        # Check for circular dependencies (simple check)
        self._check_circular_dependencies(tasks)

    def _check_circular_dependencies(self, tasks: list[Task]) -> None:
        """Check for circular dependencies in task graph.

        Args:
            tasks: List of tasks to check

        Raises:
            ValueError: If circular dependencies are detected
        """
        # Build adjacency list
        graph: dict[str, list[str]] = {task.id: task.dependencies for task in tasks}

        # Track visited nodes
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            # Check all dependencies
            for dep in graph.get(node, []):
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        # Check each task
        for task in tasks:
            if task.id not in visited:
                if has_cycle(task.id):
                    raise ValueError("Circular dependency detected in task plan")
