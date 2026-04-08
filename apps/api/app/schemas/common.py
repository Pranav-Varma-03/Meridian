from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(..., examples=["VALIDATION_ERROR"])
    message: str = Field(..., examples=["Request validation failed"])
    request_id: str = Field(..., examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    details: dict[str, Any] | None = Field(default=None)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class PaginationMeta(BaseModel):
    total: int = Field(..., examples=[120])
    limit: int = Field(..., examples=[20])
    offset: int = Field(..., examples=[0])


def error_example(code: str, message: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        }
    }


BAD_REQUEST_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Bad request",
    "content": {
        "application/json": {"example": error_example("HTTP_ERROR", "Bad request")}
    },
}

UNAUTHORIZED_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Unauthorized",
    "content": {
        "application/json": {
            "example": error_example("HTTP_ERROR", "Invalid or expired token")
        }
    },
}

NOT_FOUND_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Resource not found",
    "content": {
        "application/json": {
            "example": error_example("HTTP_ERROR", "Resource not found")
        }
    },
}

CONFLICT_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Conflict",
    "content": {
        "application/json": {
            "example": error_example("HTTP_ERROR", "Resource already exists")
        }
    },
}

VALIDATION_ERROR_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Validation error",
    "content": {
        "application/json": {
            "example": {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "details": {
                        "errors": [
                            {
                                "loc": ["body", "name"],
                                "msg": "Field required",
                                "type": "missing",
                            }
                        ]
                    },
                }
            }
        }
    },
}

INTERNAL_ERROR_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Internal server error",
    "content": {
        "application/json": {
            "example": error_example(
                "INTERNAL_SERVER_ERROR", "An unexpected error occurred"
            )
        }
    },
}

PAYLOAD_TOO_LARGE_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Payload too large",
    "content": {
        "application/json": {
            "example": error_example("HTTP_ERROR", "File too large. Max: 10MB")
        }
    },
}

UNSUPPORTED_MEDIA_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "Unsupported media type",
    "content": {
        "application/json": {
            "example": error_example(
                "HTTP_ERROR", "File type not supported. Allowed: PDF, DOCX, TXT"
            )
        }
    },
}
