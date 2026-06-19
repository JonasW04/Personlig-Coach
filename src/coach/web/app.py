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
from typing import Literal
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from coach import (
    body_mode,
    focus,
    memory,
    notification_prefs,
    plan,
    rules,
    workout_delivery,
)
from coach.agents.gemini import GeminiCoachSession, StepEvent, TextEvent
from coach.config import settings
from coach.db import SessionLocal, init_db
from coach.models import (
    ActionItem,
    ChatConversation,
    ChatMessage,
    CoachMemory,
    Goal,
    PlanDay,
    PushSubscription,
    Report,
    RecoveryRule,
)
from coach.web import stats

log = logging.getLogger("coach.web")

STATIC_DIR = Path(__file__).parent / "static"
PUBLIC_PATHS = {"/login", "/logout", "/healthz", "/sw.js", "/manifest.webmanifest", "/icon.svg"}


def _week_start(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())  # Monday


def _local_today() -> date:
    return datetime.now(ZoneInfo(settings.scheduler_timezone)).date()


# --------------------------------------------------------------------------- chat
# How many past turns to replay into a freshly built client.
_REPLAY_TURNS = 20


def _load_history(sid: str, limit: int = _REPLAY_TURNS) -> list[tuple[str, str]]:
    with SessionLocal() as s:
        rows = (
            s.query(ChatMessage)
            .filter(ChatMessage.session_id == sid)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
    return [(r.role, r.content) for r in reversed(rows)]


def _save_message(sid: str, role: str, content: str) -> None:
    if not content.strip():
        return
    with SessionLocal() as s:
        s.add(ChatMessage(session_id=sid, role=role, content=content))
        s.commit()


def _touch_conversation(sid: str, first_user_message: str) -> None:
    """Create the conversation row on first message (titled from that message),
    or just bump ``updated_at`` so it floats to the top of the history list."""
    with SessionLocal() as s:
        row = s.get(ChatConversation, sid)
        if row is None:
            title = first_user_message.strip().replace("\n", " ")
            row = ChatConversation(id=sid, title=(title[:80] or "New chat"))
            s.add(row)
        else:
            row.updated_at = _utcnow()
        s.commit()


class _Session:
    """One persistent Gemini session per browser session, so the coordinator retains
    conversation context. The lock serializes queries on a single session."""

    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.client = GeminiCoachSession(history=_load_history(sid))
        self.lock = asyncio.Lock()

    async def connect(self) -> None:
        return None


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._guard = asyncio.Lock()

    async def get(self, sid: str) -> _Session:
        async with self._guard:
            sess = self._sessions.get(sid)
            if sess is None:
                sess = _Session(sid)
                self._sessions[sid] = sess
        await sess.connect()
        return sess

    async def close_all(self) -> None:
        async with self._guard:
            for sess in self._sessions.values():
                await sess.client.close()
            self._sessions.clear()


chat_sessions = SessionManager()
sync_lock = asyncio.Lock()
# Serializes LLM plan generation so a double-click can't fire two paid runs.
plan_lock = asyncio.Lock()
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
            await asyncio.to_thread(_save_message, req.session_id, "user", req.message)
            await asyncio.to_thread(_touch_conversation, req.session_id, req.message)
            parts: list[str] = []
            seen_steps: set[str] = set()
            async for event in sess.client.events(req.message):
                if isinstance(event, TextEvent):
                    parts.append(event.text)
                    yield json.dumps({"type": "text", "text": event.text}) + "\n"
                elif isinstance(event, StepEvent) and event.label not in seen_steps:
                    seen_steps.add(event.label)
                    yield json.dumps({"type": "step", "label": event.label}) + "\n"
            await asyncio.to_thread(
                _save_message, req.session_id, "assistant", "".join(parts)
            )
            yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/chats")
async def list_chats(limit: int = 50) -> dict:
    limit = max(1, min(limit, 200))
    with SessionLocal() as s:
        rows = s.execute(
            select(ChatConversation)
            .order_by(ChatConversation.updated_at.desc())
            .limit(limit)
        ).scalars().all()
        return {
            "chats": [
                {
                    "id": r.id,
                    "title": r.title or "New chat",
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        }


@app.get("/api/chats/{sid}/messages")
async def chat_messages(sid: str) -> dict:
    with SessionLocal() as s:
        rows = (
            s.query(ChatMessage)
            .filter(ChatMessage.session_id == sid)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .all()
        )
        return {
            "messages": [
                {
                    "role": r.role,
                    "content": r.content,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }


@app.delete("/api/chats/{sid}")
async def delete_chat(sid: str) -> dict:
    with SessionLocal() as s:
        s.query(ChatMessage).filter(ChatMessage.session_id == sid).delete()
        row = s.get(ChatConversation, sid)
        if row is not None:
            s.delete(row)
        s.commit()
    await chat_sessions.close_all()
    return {"ok": True}


# ------------------------------------------------------------------------ memory
class MemoryCreate(BaseModel):
    content: str
    category: str = "note"


@app.get("/api/memories")
async def get_memories() -> dict:
    rows = await asyncio.to_thread(memory.list_memories)
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["category"], []).append(row)
    return {"memories": rows, "groups": groups}


@app.post("/api/memories")
async def add_memory(req: MemoryCreate) -> dict:
    saved = await asyncio.to_thread(
        memory.add_memory, req.content, "manual", req.category
    )
    if saved is None:
        raise HTTPException(400, "content is required")
    # New memory must reach live chat clients + future reports immediately.
    await chat_sessions.close_all()
    return saved


@app.delete("/api/memories/{memory_id}")
async def remove_memory(memory_id: int) -> dict:
    ok = await asyncio.to_thread(memory.delete_memory, memory_id)
    if not ok:
        raise HTTPException(404, "memory not found")
    await chat_sessions.close_all()
    return {"ok": True}


# ------------------------------------------------------------------------- stats
@app.get("/api/stats")
async def get_stats(start: str | None = None, end: str | None = None) -> dict:
    payload = await asyncio.to_thread(stats.activity, start, end)
    payload["goals"] = _goals_json()
    return payload


@app.get("/api/health")
async def get_health(start: str | None = None, end: str | None = None) -> dict:
    return await asyncio.to_thread(stats.health, start, end)


def _plan_response(week_start: date, days: list[PlanDay]) -> dict:
    return {
        "week_start": week_start.isoformat(),
        "days": [plan.plan_day_json(day) for day in days],
    }


def _requested_week(value: str) -> date:
    if value == "current":
        return _week_start()
    try:
        return _week_start(date.fromisoformat(value))
    except ValueError as exc:
        raise HTTPException(400, "week must be 'current' or an ISO date") from exc


class PlanGenerateRequest(BaseModel):
    week_start: date


class PlanReplanRequest(BaseModel):
    from_date: date


@app.get("/api/plan")
async def get_plan(week: str = "current") -> dict:
    week_start = _requested_week(week)
    days = await asyncio.to_thread(plan.get_week, week_start)
    return _plan_response(week_start, days)


@app.post("/api/plan/generate", response_model=None)
async def generate_plan(req: PlanGenerateRequest) -> JSONResponse | dict:
    if plan_lock.locked():
        return JSONResponse(
            {"running": True, "message": "A plan is already being generated."},
            status_code=202,
        )
    week_start = _week_start(req.week_start)
    async with plan_lock:
        try:
            days = await plan.generate_week(week_start)
        except plan.PlanGenerationError as exc:
            raise HTTPException(502, str(exc)) from exc
    deliverable = [day for day in days if day.date >= _local_today()]
    delivered = await asyncio.to_thread(workout_delivery.publish_days, deliverable)
    delivered_by_date = {day.date: day for day in delivered}
    delivered = [delivered_by_date.get(day.date, day) for day in days]
    return _plan_response(week_start, delivered)


@app.post("/api/plan/replan", response_model=None)
async def replan(req: PlanReplanRequest) -> JSONResponse | dict:
    if plan_lock.locked():
        return JSONResponse(
            {"running": True, "message": "A plan is already being generated."},
            status_code=202,
        )
    week_start = _week_start(req.from_date)
    async with plan_lock:
        try:
            days = await plan.replan_from(req.from_date)
        except plan.PlanGenerationError as exc:
            raise HTTPException(502, str(exc)) from exc
    deliverable = [day for day in days if day.date >= req.from_date]
    delivered = await asyncio.to_thread(workout_delivery.publish_days, deliverable)
    delivered_by_date = {day.date: day for day in delivered}
    delivered = [delivered_by_date.get(day.date, day) for day in days]
    return _plan_response(week_start, delivered)


@app.get("/api/plan/day/{planned_date}")
async def get_plan_day(planned_date: date) -> dict:
    with SessionLocal() as session:
        day = session.execute(
            select(PlanDay).where(PlanDay.date == planned_date)
        ).scalars().first()
    if day is None:
        raise HTTPException(404, "planned session not found")
    return plan.plan_day_json(day)


@app.post("/api/plan/day/{planned_date}/push-hevy")
async def push_plan_day_to_hevy(planned_date: date) -> dict:
    with SessionLocal() as session:
        day = session.execute(
            select(PlanDay).where(PlanDay.date == planned_date)
        ).scalars().first()
    if day is None:
        raise HTTPException(404, "planned session not found")
    if day.kind != "strength":
        raise HTTPException(400, "only strength sessions can be pushed to Hevy")
    saved = await asyncio.to_thread(workout_delivery.publish_day, planned_date)
    if saved is None:
        raise HTTPException(409, "planned session changed during Hevy push")
    if saved.delivery_status == "failed":
        raise HTTPException(502, saved.delivery_error or "Hevy delivery failed")
    return plan.plan_day_json(saved)


@app.post("/api/plan/day/{planned_date}/schedule-garmin")
async def schedule_plan_day_in_garmin(planned_date: date) -> dict:
    with SessionLocal() as session:
        day = session.execute(
            select(PlanDay).where(PlanDay.date == planned_date)
        ).scalars().first()
    if day is None:
        raise HTTPException(404, "planned session not found")
    if day.kind != "cardio":
        raise HTTPException(400, "only cardio sessions can be scheduled in Garmin")
    saved = await asyncio.to_thread(workout_delivery.publish_day, planned_date)
    if saved is None:
        raise HTTPException(409, "planned session changed during Garmin scheduling")
    if saved.delivery_status == "failed":
        raise HTTPException(502, saved.delivery_error or "Garmin delivery failed")
    return plan.plan_day_json(saved)


# ---------------------------------------------------------------- recovery rules
class RuleCondition(BaseModel):
    metric: Literal[
        "training_readiness",
        "acwr",
        "sleep_score",
        "hrv",
        "body_battery_high",
        "resting_hr",
        "avg_stress",
    ]
    op: Literal["<", "<=", ">", ">="]
    value: float


class RuleCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    condition: RuleCondition | None = None
    action: Literal["rest", "swap_to_zone2", "reduce_volume", "cap_intensity"]
    enabled: bool = True
    order_index: int | None = Field(default=None, ge=0)


class RuleUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    condition: RuleCondition | None = None
    action: Literal["rest", "swap_to_zone2", "reduce_volume", "cap_intensity"] | None = None
    enabled: bool | None = None
    order_index: int | None = Field(default=None, ge=0)


def _rule_threshold(condition: dict | None) -> float | None:
    if condition is None:
        return None
    metric = condition.get("metric")
    value = condition.get("value")
    if not isinstance(value, (int, float)):
        return None
    if metric in {"training_readiness", "sleep_score", "body_battery_high", "avg_stress"}:
        return max(0, min(100, value))
    if metric == "acwr":
        return max(0, min(100, value / 2 * 100))
    return None


def _rule_json(rule: RecoveryRule) -> dict:
    parsed = rules.condition(rule)
    return {
        "id": rule.id,
        "label": rule.label,
        "description": rule.description,
        "condition": parsed,
        "action": rule.action,
        "enabled": bool(rule.enabled),
        "order_index": rule.order_index,
        "threshold": _rule_threshold(parsed),
    }


def _latest_health_day() -> dict | None:
    days = stats.health().get("days", [])
    return days[-1] if days else None


def _rules_response() -> dict:
    with SessionLocal() as session:
        rows = list(
            session.execute(select(RecoveryRule).order_by(RecoveryRule.order_index)).scalars()
        )
    triggered = rules.evaluate(rows, _latest_health_day())
    return {
        "rules": [_rule_json(row) for row in rows],
        "triggered": [_rule_json(row) for row in triggered],
        "warning": rules.message(triggered[0]) if triggered else None,
    }


@app.get("/api/rules")
async def get_rules() -> dict:
    return _rules_response()


@app.post("/api/rules")
async def create_rule(req: RuleCreate) -> dict:
    with SessionLocal() as session:
        if req.order_index is None:
            last_order = session.execute(
                select(RecoveryRule.order_index)
                .order_by(RecoveryRule.order_index.desc())
                .limit(1)
            ).scalar_one_or_none()
            order_index = (last_order + 1) if last_order is not None else 0
        else:
            order_index = req.order_index
        session.add(
            RecoveryRule(
                label=req.label.strip(),
                description=req.description.strip(),
                condition_json=req.condition.model_dump_json() if req.condition else None,
                action=req.action,
                enabled=req.enabled,
                order_index=order_index,
            )
        )
        session.commit()
    return _rules_response()


@app.patch("/api/rules/{rule_id}")
async def update_rule(rule_id: int, req: RuleUpdate) -> dict:
    with SessionLocal() as session:
        rule = session.get(RecoveryRule, rule_id)
        if rule is None:
            raise HTTPException(404, "recovery rule not found")
        if req.label is not None:
            rule.label = req.label.strip()
        if req.description is not None:
            rule.description = req.description.strip()
        if "condition" in req.model_fields_set:
            rule.condition_json = req.condition.model_dump_json() if req.condition else None
        if req.action is not None:
            rule.action = req.action
        if req.enabled is not None:
            rule.enabled = req.enabled
        if req.order_index is not None:
            rule.order_index = req.order_index
        session.commit()
    return _rules_response()


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int) -> dict:
    with SessionLocal() as session:
        rule = session.get(RecoveryRule, rule_id)
        if rule is None:
            raise HTTPException(404, "recovery rule not found")
        session.delete(rule)
        session.commit()
    return {"ok": True}


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


class BodyModeUpdate(BaseModel):
    mode: Literal["cut", "bulk", "recomp", "perf"]


@app.get("/api/body-mode")
async def get_body_mode() -> dict:
    return await asyncio.to_thread(body_mode.get_body_mode)


@app.put("/api/body-mode")
async def update_body_mode(req: BodyModeUpdate) -> dict:
    return await asyncio.to_thread(body_mode.set_body_mode, req.mode)


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
        report_id, content, target_week = row.id, row.content, row.plan_week_start

    actions = await reports.extract_actions(content)
    count = reports.store_week_actions(
        report_id,
        actions,
        week_start=target_week,
    )
    return {"count": count}


# ------------------------------------------------------------------ notifications
class NotificationPrefUpdate(BaseModel):
    key: Literal["dailyPlan", "recoveryAlerts", "planDrift", "weeklyReview", "quietHours"]
    enabled: bool


@app.get("/api/notification-prefs")
async def get_notification_prefs() -> dict:
    return {"prefs": await asyncio.to_thread(notification_prefs.list_preferences)}


@app.put("/api/notification-prefs")
async def update_notification_pref(req: NotificationPrefUpdate) -> dict:
    prefs = await asyncio.to_thread(
        notification_prefs.set_preference, req.key, req.enabled
    )
    return {"prefs": prefs}


_NOTIFICATION_PRODUCERS = {
    "dailyPlan": "send_daily_plan",
    "recoveryAlerts": "check_recovery_alerts",
    "planDrift": "check_plan_drift",
}


class NotificationTestRequest(BaseModel):
    # Either run a real producer by its preference key, or send a plain test ping.
    kind: Literal["ping", "dailyPlan", "recoveryAlerts", "planDrift"] = "ping"


@app.post("/api/notifications/test")
async def send_test_notification(req: NotificationTestRequest) -> dict:
    """Fire a notification on demand so delivery can be verified without waiting
    for the scheduler. ``ping`` ignores preferences; producer kinds run the real
    event builder (and therefore respect the matching preference)."""
    from coach import notify, notify_producers

    if req.kind == "ping":
        used = await asyncio.to_thread(
            notify.send, "Coach test notification", "If you can read this, delivery works."
        )
        return {"kind": req.kind, "channels": used, "configured": notify.channels_configured()}

    producer = getattr(notify_producers, _NOTIFICATION_PRODUCERS[req.kind])
    used = await asyncio.to_thread(producer)
    return {"kind": req.kind, "channels": used, "configured": notify.channels_configured()}


# ----------------------------------------------------------------- scheduler health
@app.get("/api/scheduler/status")
async def scheduler_status() -> dict:
    from coach.scheduler import job_status

    return job_status()


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
        "review_date": r.review_date.isoformat() if r.review_date else None,
        "readiness_score": r.readiness_score,
        "plan_week_start": r.plan_week_start.isoformat() if r.plan_week_start else None,
        "workflow_status": r.workflow_status,
        "workflow_error": r.workflow_error,
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
    if req.kind not in ("readiness", "weekly", "health"):
        raise HTTPException(400, "kind must be 'readiness', 'weekly' or 'health'")
    from coach import reports

    try:
        report = await reports.generate_and_store(req.kind)
    except reports.ReportGenerationError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _report_json(report)


# ------------------------------------------------------------------------- focus
class FocusUpdate(BaseModel):
    focus_raw: str


@app.get("/api/focus")
async def get_focus() -> dict:
    profile = await asyncio.to_thread(focus.get_profile)
    return {**profile, "regenerating": False}


@app.post("/api/focus")
async def set_focus(req: FocusUpdate) -> dict:
    raw = req.focus_raw.strip()
    if not raw:
        raise HTTPException(400, "focus_raw is required")
    profile = await focus.set_focus(raw)
    # Drop live chat clients so the next message rebuilds them with the new
    # directive; prior turns are replayed from the DB, so context is preserved.
    await chat_sessions.close_all()
    return {**profile, "regenerating": False}


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
