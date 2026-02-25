"""
Request logging middleware.

Logs every incoming request with method, path, status code, and latency.
Uses structured logging for easy parsing by log aggregators.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("negocia.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request method, path, status code, and response time."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            status_code = response.status_code if response else 500
            logger.info(
                "%s %s → %d (%.2fms)",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
            )
