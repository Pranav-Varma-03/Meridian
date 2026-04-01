import logging
import time
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pinecone import Pinecone
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, close_db, init_db
from app.routers import chat, collections, documents, health

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def error_response(
    *,
    code: str,
    message: str,
    request_id: str,
    status_code: int,
    details: dict | None = None,
) -> JSONResponse:
    payload: dict[str, object] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Meridian API", extra={"environment": settings.environment})

    await init_db()

    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    await app.state.redis.ping()

    app.state.pinecone = Pinecone(api_key=settings.pinecone_api_key)
    app.state.db_session_factory = AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))

    logger.info("Clients initialized successfully")
    yield

    if hasattr(app.state, "redis"):
        await app.state.redis.aclose()
    await close_db()

    logger.info("Shutting down Meridian API")


app = FastAPI(
    title=settings.app_name,
    description="Production RAG System API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "unknown")
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    details = exc.detail if isinstance(exc.detail, dict) else None
    return error_response(
        code="HTTP_ERROR",
        message=detail,
        request_id=request_id,
        details=details,
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", "unknown")
    return error_response(
        code="VALIDATION_ERROR",
        message="Request validation failed",
        request_id=request_id,
        status_code=422,
        details={"errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("unhandled_exception", extra={"request_id": request_id})
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred",
        request_id=request_id,
        status_code=500,
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
