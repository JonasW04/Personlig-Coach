"""FastAPI server for the coach PWA.

Single-user app: a password-gated login sets a signed session cookie that protects
everything else. Provides a streaming chat endpoint, a combined stats dashboard API,
persisted daily/weekly reports (with on-demand generation), and the PWA shell. An
optional in-process scheduler runs the nightly sync + scheduled reports.

Run locally:
    coach-web    # http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from coach.agents.coordinator import build_options
from coach.config import settings
from coach.db import SessionLocal, init_db
from coach.models import PushSubscription, Report
from coach.web import stats

STATIC_DIR = Path(__file__).parent / "static"
PUBLIC_PATHS = {"/login", "/logout", "/healthz"}


# --------------------------------------------------------------------------- chat
class _Session:
    """One persistent SDK client per browser session, so the coordinator retains
    conversation context. The lock serializes queries on a single client."""

    def __init__(self) -> None:
        self.client = ClaudeSDKClient(options=build_options())
        self.lock = asyncio.Lock()
        self._connected = False

    async def connect(self) -> None:
        if not self._connected:
            await self.client.connect()
            self._connected = True


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._guard = asyncio.Lock()

    async def get(self, sid: str) -> _Session:
        async with self._guard:
            sess = self._sessions.get(sid)
            if sess is None:
                sess = _Session()
                self._sessions[sid] = sess
        await sess.connect()
        return sess

    async def close_all(self) -> None:
        for sess in self._sessions.values():
            if sess._connected:
                await sess.client.disconnect()
        self._sessions.clear()


chat_sessions = SessionManager()
sync_lock = asyncio.Lock()
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    init_db()
    if settings.run_scheduler:
        from coach.scheduler import build_scheduler

        _scheduler = build_scheduler()
        _scheduler.start()
    yield
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
    await chat_sessions.close_all()


app = FastAPI(title="Coach", lifespan=lifespan)


# NOTE: middleware added later runs *outermost*. require_auth reads request.session,
# so SessionMiddleware must be added AFTER it to wrap (and run before) it.
@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    authed = request.session.get("auth") is True
    public = path in PUBLIC_PATHS
    if not authed and not public:
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=False,  # behind a TLS-terminating proxy in prod; cookie still works
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)


def _require_password() -> None:
    if not settings.app_password:
        raise HTTPException(500, "APP_PASSWORD is not set on the server.")


# -------------------------------------------------------------------------- auth
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if request.session.get("auth"):
        return RedirectResponse("/", status_code=302)
    return HTMLResponse((STATIC_DIR / "login.html").read_text())


@app.post("/login")
async def login(
    request: Request, username: str = Form(""), password: str = Form("")
) -> RedirectResponse:
    _require_password()
    ok_user = secrets.compare_digest(username, settings.app_username)
    ok_pass = secrets.compare_digest(password, settings.app_password)
    if not (ok_user and ok_pass):
        return RedirectResponse("/login?error=1", status_code=302)
    request.session["auth"] = True
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/api/me")
async def me() -> dict:
    return {"username": settings.app_username}


# -------------------------------------------------------------------------- chat
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    sess = await chat_sessions.get(req.session_id)

    async def stream():
        async with sess.lock:
            await sess.client.query(req.message)
            async for message in sess.client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            yield json.dumps({"type": "text", "text": block.text}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ------------------------------------------------------------------------- stats
@app.get("/api/stats")
async def get_stats(start: str | None = None, end: str | None = None) -> dict:
    return await asyncio.to_thread(stats.activity, start, end)


@app.post("/api/sync", response_model=None)
async def sync_data() -> JSONResponse | dict:
    if sync_lock.locked():
        return JSONResponse(
            {"running": True, "message": "Sync already running."},
            status_code=202,
        )

    async with sync_lock:
        from coach import sync

        result = await asyncio.to_thread(sync.run)
        return {"running": False, **result}


# ------------------------------------------------------------------ notifications
class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


@app.get("/api/push/config")
async def push_config() -> dict:
    enabled = bool(
        settings.web_push_vapid_public_key
        and settings.web_push_vapid_private_key
        and settings.web_push_vapid_subject
    )
    return {
        "enabled": enabled,
        "public_key": settings.web_push_vapid_public_key if enabled else None,
    }


@app.post("/api/push/subscribe")
async def push_subscribe(req: PushSubscriptionRequest, request: Request) -> dict:
    if not settings.web_push_vapid_public_key or not settings.web_push_vapid_private_key:
        raise HTTPException(400, "Web Push is not configured on the server.")

    user_agent = request.headers.get("user-agent")
    with SessionLocal() as s:
        existing = s.execute(
            select(PushSubscription).where(PushSubscription.endpoint == req.endpoint)
        ).scalars().first()
        if existing:
            existing.p256dh = req.keys.p256dh
            existing.auth = req.keys.auth
            existing.user_agent = user_agent
        else:
            s.add(PushSubscription(
                endpoint=req.endpoint,
                p256dh=req.keys.p256dh,
                auth=req.keys.auth,
                user_agent=user_agent,
            ))
        s.commit()
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(req: PushUnsubscribeRequest) -> dict:
    with SessionLocal() as s:
        existing = s.execute(
            select(PushSubscription).where(PushSubscription.endpoint == req.endpoint)
        ).scalars().first()
        if existing:
            s.delete(existing)
            s.commit()
    return {"ok": True}


# ----------------------------------------------------------------------- reports
def _report_json(r: Report) -> dict:
    return {
        "id": r.id,
        "kind": r.kind,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "content": r.content,
    }


@app.get("/api/reports")
async def list_reports(kind: str | None = None, limit: int = 20) -> dict:
    limit = max(1, min(limit, 100))
    with SessionLocal() as s:
        q = select(Report).order_by(Report.created_at.desc()).limit(limit)
        if kind:
            q = select(Report).where(Report.kind == kind).order_by(
                Report.created_at.desc()
            ).limit(limit)
        rows = s.execute(q).scalars().all()
        return {"reports": [_report_json(r) for r in rows]}


class GenerateRequest(BaseModel):
    kind: str  # 'readiness' | 'weekly'


@app.post("/api/reports/generate")
async def generate_report(req: GenerateRequest) -> dict:
    if req.kind not in ("readiness", "weekly"):
        raise HTTPException(400, "kind must be 'readiness' or 'weekly'")
    from coach import reports

    report = await reports.generate_and_store(req.kind)
    return _report_json(report)


# Serve the PWA shell. Mounted last so it doesn't shadow API/auth routes.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
