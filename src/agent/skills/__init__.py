"""Skill Registry — extensible tool system for Sparki ReAct Agent."""

from src.agent.skills.base import Skill, Parameter
from src.agent.skills.registry import SkillRegistry
from src.agent.skills.core_tools import register_core_tools

__all__ = [
    "Skill",
    "Parameter",
    "SkillRegistry",
    "register_core_tools",
]