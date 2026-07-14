import json
import logging
import time
from collections import Counter, defaultdict, deque
from contextvars import ContextVar
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import JSONResponse

correlation_id = ContextVar("correlation_id", default="-")
_metrics = Counter()
_rate_events = defaultdict(deque)
_lock = Lock()

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record), "level": record.levelname,
            "logger": record.name, "message": record.getMessage(),
            "correlation_id": correlation_id.get(),
        }, ensure_ascii=False)

def configure_logging():
    handler = logging.StreamHandler(); handler.setFormatter(JsonFormatter())
    root = logging.getLogger(); root.handlers = [handler]; root.setLevel(logging.INFO)

def increment(name: str, value: int = 1):
    with _lock: _metrics[name] += value

def metrics_snapshot():
    with _lock: return dict(_metrics)

def enforce_rate_limit(user_id: int, operation: str, limit: int, window_seconds: int = 60):
    now = time.monotonic(); key = (user_id, operation)
    with _lock:
        events = _rate_events[key]
        while events and now - events[0] >= window_seconds: events.popleft()
        if len(events) >= limit:
            _metrics["wallet_rate_limit_rejections_total"] += 1
            raise HTTPException(429, "Too many requests. Please try again later")
        events.append(now)

async def correlation_middleware(request, call_next):
    request_id = request.headers.get("X-Correlation-ID") or uuid4().hex
    token = correlation_id.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request_id
        increment(f"http_status_{response.status_code}_total")
        return response
    except Exception:
        logging.getLogger("app.request").exception("Unhandled request error")
        return JSONResponse(500, {"detail": "Internal server error", "correlation_id": request_id})
    finally:
        correlation_id.reset(token)
