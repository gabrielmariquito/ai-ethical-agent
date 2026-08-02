from __future__ import annotations

import json


class ApiError(Exception):
    """Raised by a route handler to short-circuit with a specific HTTP
    status; httphandler.py catches this and serializes it, so handlers never
    need to touch the response machinery directly for the error path."""

    def __init__(self, status: int, error: str, message: str):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message

    def to_bytes(self) -> bytes:
        return json.dumps(
            {"error": self.error, "message": self.message}, ensure_ascii=False
        ).encode("utf-8")


def bad_request(error: str, message: str) -> ApiError:
    return ApiError(400, error, message)


def not_found(error: str, message: str) -> ApiError:
    return ApiError(404, error, message)
