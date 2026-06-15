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
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from coach import focus
from coach.agents.coordinator import build_options
from coach.config import settings
from coach.db import SessionLocal, init_db
from coach.models import ActionItem, Goal, PushSubscription, Report
from coach.web import stats

log = logging.getLogger("coach.web")

STATIC_DIR = Path(__file__).parent / "static"
PUBLIC_PATHS = {"/login", "/logout", "/healthz", "/sw.js", "/manifest.webmanifest", "/icon.svg"}


def _week_start(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())  # Monday


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
# Tracks the background regeneration of reports kicked off when the focus changes.
_focus_regen = {"running": False, "kinds": [], "error": None}


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


DEFAULT_GOALS = [
    {
        "key": "weekly_strength_sessions",
        "label": "Strength sessions",
        "metric": "weekly_strength_sessions",
        "target_value": 3.0,
        "unit": "sessions",
        "direction": "at_least",
        "scope": "This week",
    },
    {
        "key": "weekly_active_days",
        "label": "Active days",
        "metric": "weekly_active_days",
        "target_value": 4.0,
        "unit": "days",
        "direction": "at_least",
        "scope": "This week",
    },
    {
        "key": "weekly_cardio_distance",
        "label": "Cardio distance",
        "metric": "weekly_cardio_distance",
        "target_value": 15.0,
        "unit": "km",
        "direction": "at_least",
        "scope": "This week",
    },
    {
        "key": "weekly_strength_volume",
        "label": "Strength volume",
        "metric": "weekly_strength_volume",
        "target_value": 20000.0,
        "unit": "kg",
        "direction": "at_least",
        "scope": "This week",
    },
    {
        "key": "body_weight",
        "label": "Body weight",
        "metric": "body_weight",
        "target_value": None,
        "unit": "kg",
        "direction": "toward",
        "scope": "Latest",
    },
    {
        "key": "body_fat",
        "label": "Body fat",
        "metric": "body_fat",
        "target_value": None,
        "unit": "%",
        "direction": "at_most",
        "scope": "Latest",
    },
]
GOAL_SPECS = {g["key"]: g for g in DEFAULT_GOALS}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _goals_json() -> list[dict]:
    with SessionLocal() as s:
        saved = {g.key: g for g in s.execute(select(Goal)).scalars().all()}
    out = []
    for spec in DEFAULT_GOALS:
        row = saved.get(spec["key"])
        goal = {**spec}
        if row is not None:
            goal["target_value"] = row.target_value
            goal["enabled"] = row.enabled
            goal["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
        else:
            goal["enabled"] = True
            goal["updated_at"] = None
        out.append(goal)
    return out


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
    payload = await asyncio.to_thread(stats.activity, start, end)
    payload["goals"] = _goals_json()
    return payload


class GoalUpdate(BaseModel):
    key: str
    target_value: float | None = None
    enabled: bool = True


class GoalsUpdate(BaseModel):
    goals: list[GoalUpdate]


@app.get("/api/goals")
async def list_goals() -> dict:
    return {"goals": _goals_json()}


@app.put("/api/goals")
async def update_goals(req: GoalsUpdate) -> dict:
    with SessionLocal() as s:
        for item in req.goals:
            if item.key not in GOAL_SPECS:
                raise HTTPException(400, f"Unknown goal key: {item.key}")
            row = s.get(Goal, item.key)
            if row is None:
                row = Goal(key=item.key)
                s.add(row)
            row.target_value = item.target_value
            row.enabled = item.enabled
        s.commit()
    return {"goals": _goals_json()}


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


# ------------------------------------------------------------------- action plan
def _action_json(item: ActionItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "week_start": item.week_start.isoformat() if item.week_start else None,
        "metric": item.metric,
        "target_value": item.target_value,
        "auto": bool(item.auto),
        "source_report_id": item.source_report_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


class ActionCreate(BaseModel):
    title: str
    due_date: date | None = None
    metric: str | None = None
    target_value: float | None = None
    source_report_id: int | None = None


class ActionUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    due_date: date | None = None


@app.get("/api/actions")
async def list_actions(
    status: str | None = None, week: str | None = None, limit: int = 100
) -> dict:
    limit = max(1, min(limit, 200))
    with SessionLocal() as s:
        q = select(ActionItem)
        if status:
            q = q.where(ActionItem.status == status)
        if week == "current":
            q = q.where(ActionItem.week_start == _week_start())
        q = q.order_by(ActionItem.created_at.desc()).limit(limit)
        rows = s.execute(q).scalars().all()
    return {"actions": [_action_json(row) for row in rows]}


@app.post("/api/actions")
async def create_action(req: ActionCreate) -> dict:
    title = req.title.strip()
    if not title:
        raise HTTPException(400, "title is required")
    metric = req.metric if req.metric in GOAL_SPECS else None
    with SessionLocal() as s:
        item = ActionItem(
            title=title,
            due_date=req.due_date,
            week_start=_week_start(),
            metric=metric,
            target_value=req.target_value,
            source_report_id=req.source_report_id,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        s.expunge(item)
    return _action_json(item)


@app.patch("/api/actions/{item_id}")
async def update_action(item_id: int, req: ActionUpdate) -> dict:
    with SessionLocal() as s:
        item = s.get(ActionItem, item_id)
        if item is None:
            raise HTTPException(404, "action not found")
        if req.title is not None:
            title = req.title.strip()
            if not title:
                raise HTTPException(400, "title cannot be empty")
            item.title = title
        if req.due_date is not None:
            item.due_date = req.due_date
        if req.status is not None:
            if req.status not in {"open", "done"}:
                raise HTTPException(400, "status must be open or done")
            item.status = req.status
            item.completed_at = _utcnow() if req.status == "done" else None
        s.commit()
        s.refresh(item)
        s.expunge(item)
    return _action_json(item)


@app.delete("/api/actions/{item_id}")
async def delete_action(item_id: int) -> dict:
    with SessionLocal() as s:
        item = s.get(ActionItem, item_id)
        if item is None:
            raise HTTPException(404, "action not found")
        s.delete(item)
        s.commit()
    return {"ok": True}


@app.post("/api/actions/import-latest")
async def import_latest_actions() -> dict:
    """Re-extract and store structured actions from the latest weekly review.

    Useful when the user wants to refresh their plan mid-week, or when an older
    report was generated before structured extraction was available.
    """
    from coach import reports

    with SessionLocal() as s:
        row = s.execute(
            select(Report).where(Report.kind == "weekly").order_by(Report.created_at.desc()).limit(1)
        ).scalars().first()
        if row is None:
            raise HTTPException(404, "No weekly review found. Generate one first.")
        report_id, content = row.id, row.content

    actions = await reports.extract_actions(content)
    count = reports.store_week_actions(report_id, actions)
    return {"count": count}


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


# ------------------------------------------------------------------------- focus
class FocusUpdate(BaseModel):
    focus_raw: str


async def _regenerate_reports(kinds: tuple[str, ...]) -> None:
    """Regenerate standing reports so they reflect a freshly-changed focus."""
    from coach import reports

    _focus_regen.update(running=True, kinds=list(kinds), error=None)
    try:
        for kind in kinds:
            try:
                await reports.generate_and_store(kind)
            except Exception as exc:  # noqa: BLE001
                log.exception("focus regen failed for %s", kind)
                _focus_regen["error"] = str(exc)
    finally:
        _focus_regen.update(running=False, kinds=[])


@app.get("/api/focus")
async def get_focus() -> dict:
    profile = await asyncio.to_thread(focus.get_profile)
    return {**profile, "regenerating": _focus_regen["running"]}


@app.post("/api/focus")
async def set_focus(req: FocusUpdate) -> dict:
    raw = req.focus_raw.strip()
    if not raw:
        raise HTTPException(400, "focus_raw is required")
    profile = await focus.set_focus(raw)
    # Regenerate the standing reports in the background so they immediately
    # represent the new focus; the client polls /api/focus for completion.
    asyncio.create_task(_regenerate_reports(("readiness", "weekly")))
    return {**profile, "regenerating": True}


@app.get("/sw.js")
async def get_sw() -> FileResponse:
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    return FileResponse(STATIC_DIR / "sw.js", headers=headers, media_type="application/javascript")


# Serve the PWA shell. Mounted last so it doesn't shadow API/auth routes.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
