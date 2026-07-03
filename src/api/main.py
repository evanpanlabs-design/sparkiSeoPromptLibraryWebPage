"""FastAPI application lifecycle and route aggregation."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.memory import init_db, close
from src.api import agent_routes, prompt_routes, category_routes, queries_routes

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup, close connection on shutdown."""
    init_db()
    logger.info("database initialized")
    yield
    close()
    logger.info("database connection closed")


app = FastAPI(
    title="Sparki API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(agent_routes.router, tags=["Agent"])
app.include_router(prompt_routes.router, tags=["Prompts"])
app.include_router(prompt_routes.images_router, tags=["Images"])
app.include_router(category_routes.router, tags=["Categories"])
app.include_router(queries_routes.router, tags=["Queries"])
app.include_router(queries_routes.authors_router, tags=["Authors"])