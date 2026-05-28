import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv

_env_path = __file__.rsplit("/", 3)[0] + "/.env"
if os.path.exists(_env_path):
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from investigator.agent.coral_client import CoralClient
from investigator.agent.core import AgentCore
from investigator.lib.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

coral: Optional[CoralClient] = None
rate_limiter = RateLimiter(max_requests=20, window_seconds=60.0)
_HTML_DIR = os.path.join(os.path.dirname(__file__), "templates")
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global coral
    coral = CoralClient()
    try:
        await coral.connect()
        logger.info("Coral MCP connected")
    except Exception as e:
        logger.warning("Coral MCP connection failed (mock sources may still work): %s", e)
    yield
    if coral and coral.is_connected:
        await coral.disconnect()
        logger.info("Coral MCP disconnected")


app = FastAPI(title="Incident Root-Cause Investigator", lifespan=lifespan)

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
async def health():
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
):
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in 60 seconds.")

    safe_service = AgentCore._sanitize_service(service)

    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if not coral or not coral.is_connected:
        return HTMLResponse(
            json.dumps({"error": "Coral not connected. Cannot investigate."}),
            status_code=503,
            media_type="application/json",
        )

    async def event_stream():
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
                agent = AgentCore(coral, incidents_channel="incidents")
                report = await agent.investigate_with_reasoning(
                    question=question,
                    on_progress=on_progress,
                    on_phase2_query=on_phase2_query,
                    since=since,
                    service=safe_service,
                )
                await queue.put(("complete", report))
            except Exception:
                logger.exception("Investigation failed for IP=%s question=%r", client_ip, question[:200])
                await queue.put(("error", {"message": "An internal error occurred during investigation."}))

        task = asyncio.create_task(run_investigation())

        while True:
            event_type, data = await queue.get()
            serialized = json.dumps(data, default=str, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {serialized}\n\n"
            if event_type in ("complete", "error"):
                break

        task = None

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
