from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import get_settings
from app.routers import health, documents, chat, collections

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Meridian API...")
    # TODO: Initialize connections (DB, Redis, Pinecone)
    yield
    logger.info("Shutting down Meridian API...")
    # TODO: Close connections


app = FastAPI(
    title=settings.app_name,
    description="Production RAG System API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, tags=["Health"])
app.include_router(
    documents.router,
    prefix=f"{settings.api_v1_prefix}/documents",
    tags=["Documents"],
)
app.include_router(
    collections.router,
    prefix=f"{settings.api_v1_prefix}/collections",
    tags=["Collections"],
)
app.include_router(
    chat.router,
    prefix=f"{settings.api_v1_prefix}/chat",
    tags=["Chat"],
)


@app.get("/")
async def root():
    return {"message": "Meridian RAG API", "version": "0.1.0"}
