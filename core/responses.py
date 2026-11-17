"""
core/responses.py
-----------------
Consistent API response formatting and helpers for ExamProctor API v1.
Uses FastAPI jsonable_encoder to handle datetimes, Pydantic objects, and collections cleanly.
"""
from typing import Any, Optional, Dict
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import status

def success_response(
    data: Any = None,
    message: str = "Success",
    meta: Optional[Dict[str, Any]] = None,
    status_code: int = status.HTTP_200_OK
) -> JSONResponse:
    """Format a consistent success response."""
    payload: Dict[str, Any] = {
        "success": True,
        "message": message,
        "data": data
    }
    if meta is not None:
        payload["meta"] = meta
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))

def error_response(
    message: str = "An error occurred",
    code: str = "BAD_REQUEST",
    details: Any = None,
    status_code: int = status.HTTP_400_BAD_REQUEST
) -> JSONResponse:
    """Format a consistent error response."""
    payload: Dict[str, Any] = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details
        }
    }
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))
