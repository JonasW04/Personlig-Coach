"""One-time Strava OAuth authorization. Run: `coach-strava-auth`.

Opens the Strava consent page in your browser, captures the redirect on a local
callback server, exchanges the code for tokens, and stores them in the DB.

Prerequisite: a Strava API app (https://www.strava.com/settings/api) with its
"Authorization Callback Domain" set to `localhost`.
"""
from __future__ import annotations

import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from coach.config import settings
from coach.db import init_db
from coach.integrations.strava import TOKEN_URL, save_tokens

PORT = 8721
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPE = "activity:read_all"

_code: str | None = None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        global _code
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = "Strava authorized. You can close this tab." if _code else "Authorization failed."
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *args):  # silence default logging
        pass


def main() -> None:
    if not settings.strava_client_id or not settings.strava_client_secret:
        raise SystemExit("Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env first.")

    init_db()

    auth_url = "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(
        {
            "client_id": settings.strava_client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": SCOPE,
        }
    )
    print(f"Opening browser to authorize Strava...\nIf it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", PORT), _Handler)
    while _code is None:
        server.handle_request()

    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "code": _code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    save_tokens(data["access_token"], data["refresh_token"], data["expires_at"])
    athlete = data.get("athlete", {})
    print(f"Authorized {athlete.get('firstname', '')} {athlete.get('lastname', '')}. Tokens saved.")
    print("Now run `coach-sync` to pull your activities.")


if __name__ == "__main__":
    main()
