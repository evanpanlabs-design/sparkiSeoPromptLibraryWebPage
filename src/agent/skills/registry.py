"""SkillRegistry — extensible tool registration and discovery."""

from typing import Optional

from src.agent.skills.base import Skill


class SkillRegistry:
    """Registry for all available Skills (tools)."""

    def __init__(self) -> None:
        self._tools: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Register a skill. Raises ValueError if name already exists."""
        if skill.name in self._tools:
            raise ValueError(f"Skill '{skill.name}' already registered")
        self._tools[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """Get skill by name. Returns None if not found."""
        return self._tools.get(name)

    def list_all(self) -> list[str]:
        """List all registered skill names."""
        return list(self._tools.keys())

    def list_by_category(self, category: str) -> list[Skill]:
        """List all skills in a category."""
        return [s for s in self._tools.values() if s.category == category]

    def get_tool_schemas(self) -> list[dict]:
        """Return JSON schema list for all tools (for LLM function calling).

        Format: [{"name": "...", "description": "...", "parameters": {...}}, ...]
        """
        schemas = []
        for skill in self._tools.values():
            properties: dict[str, dict[str, Any]] = {}
            required: list[str] = []
            for param in skill.parameters:
                prop: dict[str, Any] = {"description": param.description}
                if param.type:
                    prop["type"] = param.type
                if param.enum:
                    prop["enum"] = param.enum
                if param.default is not None:
                    prop["default"] = param.default
                properties[param.name] = prop
                if param.required:
                    required.append(param.name)

            schema = {
                "name": skill.name,
                "description": skill.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
            schemas.append(schema)
        return schemas

    def get_categories(self) -> list[str]:
        """Return all unique categories."""
        return list({s.category for s in self._tools.values()})