import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("knowledge-rag")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        error_id = uuid4().hex[:10]
        logger.exception("Unhandled exception (error_id=%s)", error_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error. Reference: {error_id}"},
        )
