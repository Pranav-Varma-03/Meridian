import logging
import time
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pinecone import Pinecone
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, close_db, init_db
from app.core.observability import (
    DependencySpan,
    build_route_template_registry,
    classify_application_failure,
    configure_application_logging,
    initialize_observability,
    lifecycle_event,
    record_http_observation,
    resolve_route_template,
    shutdown_observability,
)
from app.routers import (
    auth_diagnostics,
    chat,
    collections,
    documents,
    health,
    ingest,
    users,
)

settings = get_settings()

configure_application_logging(settings.log_level)
logger = logging.getLogger(__name__)
initialize_observability(settings)
tracer = trace.get_tracer("meridian.api")


def error_response(
    *,
    code: str,
    message: str,
    request_id: str,
    status_code: int,
    details: dict | None = None,
    headers: dict[str, str] | None = None,
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
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    lifecycle_event(logger, "api_starting", environment=settings.environment)

    await init_db()

    app.state.redis = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    with DependencySpan("redis", "startup_ping"):
        await app.state.redis.ping()

    with DependencySpan("pinecone", "client_initialize"):
        app.state.pinecone = Pinecone(api_key=settings.pinecone_api_key)
    app.state.db_session_factory = AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        with DependencySpan("postgres", "startup_ping"):
            await session.execute(text("SELECT 1"))

    lifecycle_event(logger, "api_clients_initialized")
    yield

    if hasattr(app.state, "redis"):
        await app.state.redis.aclose()
    await close_db()

    lifecycle_event(logger, "api_stopped")
    shutdown_observability()


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
    with tracer.start_as_current_span("http.request") as span:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        route_template = resolve_route_template(request.scope, ROUTE_TEMPLATES)
        span.set_attribute("http.request.method", request.method)
        span.set_attribute("http.route", route_template)
        span.set_attribute("http.response.status_code", response.status_code)
        span.set_attribute("meridian.request.duration_ms", duration_ms)
        if response.status_code >= 500:
            span.set_status(trace.Status(trace.StatusCode.ERROR))
        record_http_observation(
            method=request.method,
            route=route_template,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["x-request-id"] = request_id
        lifecycle_event(
            logger,
            "request_completed",
            method=request.method,
            route=route_template,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "unknown")
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    details = exc.detail if isinstance(exc.detail, dict) else None
    code = "HTTP_ERROR"
    if isinstance(exc.detail, dict):
        code = str(exc.detail.get("code", code))
        detail = str(exc.detail.get("message", detail))
    return error_response(
        code=code,
        message=detail,
        request_id=request_id,
        details=details,
        status_code=exc.status_code,
        headers=exc.headers,
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
    lifecycle_event(
        logger,
        "unhandled_exception",
        level=logging.ERROR,
        request_id=request_id,
        outcome="failed",
        failure_class=classify_application_failure(exc),
        error_type=type(exc).__name__,
    )
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
app.include_router(
    users.router,
    prefix=f"{settings.api_v1_prefix}/users",
    tags=["Users"],
)
app.include_router(
    ingest.router,
    prefix=f"{settings.api_v1_prefix}/ingest",
    tags=["Ingestion"],
)
app.include_router(
    auth_diagnostics.router,
    prefix=f"{settings.api_v1_prefix}/auth",
    tags=["Auth diagnostics"],
)


@app.get("/")
async def root():
    return {"message": "Meridian RAG API", "version": "0.1.0"}


ROUTE_TEMPLATES = build_route_template_registry(app.routes)
