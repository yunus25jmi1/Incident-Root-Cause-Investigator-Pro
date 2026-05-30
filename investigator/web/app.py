import asyncio
import json
import logging
import os
import signal
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

_env_path = __file__.rsplit("/", 3)[0] + "/.env"
if os.path.exists(_env_path):
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware

from investigator.agent.coral_client import CoralClient
from investigator.agent.core import AgentCore
from investigator.agent.reasoning import ReasoningEngine
from investigator.lib.rate_limiter import RateLimiter
from investigator.lib.secrets_refresher import SecretsRefresher
from investigator.lib.redis_persistence import RedisRateLimiter

logger = logging.getLogger(__name__)

secrets_refresher = SecretsRefresher()
coral: Optional[CoralClient] = None
_redis_rl = RedisRateLimiter(max_requests=20, window_seconds=60.0)
rate_limiter = _redis_rl if _redis_rl._r else RateLimiter(max_requests=20, window_seconds=60.0)
_HTML_DIR = os.path.join(os.path.dirname(__file__), "templates")
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

_API_KEY = os.environ.get("API_KEY", "").strip()
_SECURITY_SCHEME = HTTPBearer(auto_error=False)

async def verify_api_key(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_SECURITY_SCHEME)):
    if _API_KEY:
        if not credentials or credentials.credentials != _API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key. Provide via Authorization: Bearer <key> or set API_KEY env var.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global coral
    _dsn = os.environ.get("SENTRY_DSN", "").strip()
    if _dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=_dsn, traces_sample_rate=0.1)
            logger.info("Sentry SDK initialized")
        except Exception as e:
            logger.warning("Failed to init Sentry SDK: %s", e)
    coral = CoralClient()
    try:
        await coral.connect()
        logger.info("Coral MCP connected")
    except Exception as e:
        logger.warning("Coral MCP connection failed (mock sources may still work): %s", e)

    _shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_shutdown()))
        except NotImplementedError:
            pass

    async def _shutdown():
        logger.info("Shutdown signal received — draining...")
        _shutdown_event.set()

    yield

    if _shutdown_event.is_set():
        logger.info("Graceful shutdown complete")
    if coral and coral.is_connected:
        await coral.disconnect()
        logger.info("Coral MCP disconnected")


app = FastAPI(title="Incident Root-Cause Investigator", lifespan=lifespan)

_MAX_REQUEST_BODY = 1024 * 10  # 10 KB


class RequestBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_REQUEST_BODY:
            raise HTTPException(status_code=413, detail="Request body too large")
        return await call_next(request)


app.add_middleware(RequestBodySizeMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def index():
    html_path = os.path.join(_HTML_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Investigator Web UI</h1><p>Template not found.</p>")


@app.get("/api/health")
async def health(credentials: Optional[HTTPAuthorizationCredentials] = Depends(verify_api_key)):
    return {
        "status": "ok",
        "coral_connected": coral.is_connected if coral else False,
    }


@app.get("/api/investigate")
async def investigate(
    request: Request,
    question: str = Query(..., max_length=5000, description="Investigation question"),
    since: str = Query("3h", max_length=20, description="Time window (e.g. 3h, 30m)"),
    service: str = Query("", max_length=200, description="Service name filter"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(verify_api_key),
):
    client_ip = request.client.host if request.client else "unknown"
    if await rate_limiter.is_rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in 60 seconds.")

    await secrets_refresher.refresh_if_changed()

    safe_service = AgentCore._sanitize_service(service)

    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    logger.info("Investigate request from IP=%s: question=%r, service=%r", client_ip, question[:200], safe_service)

    if not coral or not coral.is_connected:
        return HTMLResponse(
            json.dumps({"error": "Coral not connected. Cannot investigate."}),
            status_code=503,
            media_type="application/json",
        )

    async def event_stream():
        try:
            queue: asyncio.Queue = asyncio.Queue()

            async def on_progress(emoji: str, text: str) -> None:
                await queue.put(("progress", {"emoji": emoji, "text": text}))

            async def on_phase2_query(data: dict) -> None:
                await queue.put(("phase2_query", {
                    "sql": data.get("sql", ""),
                    "row_count": data.get("row_count", 0),
                }))

            async def run_investigation():
                try:
                    reasoning = ReasoningEngine()
                    intent = await reasoning.classify_intent(question)

                    if intent == "lookup":
                        phase1 = await AgentCore.run_phase1_queries(coral, since=since, service=safe_service)
                        answer = await reasoning.lookup_answer(question, phase1, coral.query)
                        await queue.put(("complete", {
                            "question": question,
                            "answer": answer,
                            "summary": answer,
                            "sources": {k: {"status": "ok" if v.get("rows") else "empty", "count": len(v.get("rows", []))} for k, v in phase1.items()},
                            "confidence": "High",
                            "evidence_chain": [],
                            "people_involved": [],
                            "suggested_actions": [],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "phase2_run": False,
                        }))
                        return

                    agent = AgentCore(coral, incidents_channel="incidents")
                    report = await agent.investigate_with_reasoning(
                        question=question,
                        on_progress=on_progress,
                        on_phase2_query=on_phase2_query,
                        since=since,
                        service=safe_service,
                    )
                    await queue.put(("complete", report))
                except asyncio.CancelledError:
                    logger.info("Investigation cancelled for IP=%s", client_ip)
                except Exception:
                    logger.exception("Investigation failed for IP=%s question=%r", client_ip, question[:200])
                    await queue.put(("error", {"message": "An internal error occurred during investigation."}))

            task = asyncio.create_task(run_investigation())

            try:
                while True:
                    try:
                        event_type, data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            task.cancel()
                            logger.info("Client disconnected — cancelled investigation for IP=%s", client_ip)
                            break
                        continue
                    serialized = json.dumps(data, default=str, ensure_ascii=False)
                    yield f"event: {event_type}\ndata: {serialized}\n\n"
                    if event_type in ("complete", "error"):
                        break
            finally:
                if not task.done():
                    task.cancel()
        except Exception:
            logger.exception("SSE generator failed for IP=%s", client_ip)
            yield f"event: error\ndata: {json.dumps({'message': 'Investigation stream failed. Please try again.'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
