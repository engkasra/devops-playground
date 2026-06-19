"""
Minimal FastAPI service for the DevOps assessment.

The business logic is intentionally trivial. The point of this service is to be
a realistic target for Docker, Kubernetes, monitoring and logging.

Features that the infrastructure relies on:
  * Configuration is read entirely from environment variables.
  * /health   -> liveness  (process is up)
  * /ready    -> readiness (startup finished / dependencies OK)
  * /metrics  -> Prometheus metrics
  * Every request is logged as a single structured JSON line (Loki/ELK friendly).
"""

import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

# --------------------------------------------------------------------------- #
# Configuration (12-factor: everything comes from the environment)
# --------------------------------------------------------------------------- #
APP_NAME = os.getenv("APP_NAME", "devops-demo")
APP_ENV = os.getenv("APP_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# Demonstrates consuming a value that arrives via a Kubernetes Secret.
API_TOKEN = os.getenv("API_TOKEN", "")


# --------------------------------------------------------------------------- #
# Structured JSON logging
# --------------------------------------------------------------------------- #
# Attributes that already exist on a standard LogRecord. Anything passed via
# `extra={...}` that is NOT in this set gets merged into the JSON output, so we
# can attach request_id, method, path, etc. without extra plumbing.
_STD_RECORD_KEYS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_RECORD_KEYS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL)
    # Make uvicorn's access/error logs flow through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = [handler]
    return logging.getLogger(APP_NAME)


log = setup_logging()

# In-memory readiness flag, flipped during the lifespan startup phase.
_state = {"ready": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("service starting", extra={"event": "startup", "env": APP_ENV})
    # In a real app you would check DB/cache connectivity here before flipping.
    _state["ready"] = True
    yield
    _state["ready"] = False
    log.info("service stopping", extra={"event": "shutdown"})


app = FastAPI(title=APP_NAME, version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info(
        "request handled",
        extra={
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/")
async def root():
    return {
        "app": APP_NAME,
        "env": APP_ENV,
        "message": "Hello from the DevOps assessment service",
    }


@app.get("/api/items")
async def items():
    """Trivial placeholder 'business logic'."""
    return {"items": ["alpha", "beta", "gamma"], "count": 3}


@app.get("/health")
async def health():
    """Liveness probe: returns 200 as long as the process can serve requests."""
    return {"status": "alive"}


@app.get("/ready")
async def ready():
    """Readiness probe: 200 only once startup finished / dependencies are OK."""
    if _state["ready"]:
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not_ready"})


# Exposes GET /metrics in Prometheus text format and records default HTTP metrics.
Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)
