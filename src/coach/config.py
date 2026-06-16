from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    hevy_api_key: str = ""

    # Strava OAuth app credentials (https://www.strava.com/settings/api)
    strava_client_id: str = ""
    strava_client_secret: str = ""

    # Withings OAuth app credentials (https://developer.withings.com/)
    withings_client_id: str = ""
    withings_client_secret: str = ""

    database_url: str = "postgresql+psycopg://jonaswiger@localhost:5433/coach"

    coach_model: str = "gemini-3.5-flash"
    coach_review_model: str = "gemini-3.5-flash"
    # Cheap/fast model for tool-less utility transforms (directive expansion,
    # action-plan extraction).
    coach_utility_model: str = "gemini-3.5-flash"
    coach_reasoning_effort: str = "high"

    # Email notifications (SMTP). For Gmail, use an App Password as smtp_password.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    # Notion notifications. Create an internal integration
    # (https://www.notion.so/my-integrations), share a parent page with it, and
    # paste that page's id here. Reviews/readiness are added as child pages.
    notion_api_key: str = ""
    notion_parent_page_id: str = ""

    # Web Push notifications for installed PWAs. Generate VAPID keys once and keep
    # them stable; changing keys invalidates existing browser subscriptions.
    web_push_vapid_public_key: str = ""
    web_push_vapid_private_key: str = ""
    web_push_vapid_subject: str = "mailto:coach@example.com"

    # Web app auth (single user). APP_PASSWORD gates login; SESSION_SECRET signs
    # the session cookie (set a long random value in production).
    app_username: str = "me"
    app_password: str = ""
    session_secret: str = "dev-insecure-change-me"

    # Web server. Railway provides $PORT; bind 0.0.0.0 there.
    port: int = 8000
    host: str = "127.0.0.1"

    # Run the in-process scheduler (nightly sync, daily readiness, weekly review).
    # Enable on the always-on web service in production.
    run_scheduler: bool = False
    scheduler_timezone: str = "UTC"

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Railway/Heroku hand out postgres:// or postgresql:// URLs, but our
        # SQLAlchemy engine needs the psycopg v3 driver explicitly.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

settings = Settings()
