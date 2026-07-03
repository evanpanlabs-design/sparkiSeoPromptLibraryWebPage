"""Sparki Memory persistence layer — SQLite-backed storage for all pipeline data."""

from src.memory.schema import init_db, close
from src.memory.queries import QueryRepository
from src.memory.authors import AuthorRepository
from src.memory.prompts import PromptRepository, PromptRecord, PromptWithAuthor
from src.memory.scrape_runs import ScrapeRunRepository, ScrapeRun

__all__ = [
    # Schema
    "init_db",
    "close",
    # Repositories
    "QueryRepository",
    "AuthorRepository",
    "PromptRepository",
    "ScrapeRunRepository",
    # Data classes
    "PromptRecord",
    "PromptWithAuthor",
    "ScrapeRun",
]
