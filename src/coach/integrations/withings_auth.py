"""One-time Withings OAuth authorization. Run: `coach-withings-auth`.

Opens the Withings consent page in your browser, captures the redirect on a local
callback server, exchanges the code for tokens, and stores them in the DB.

Prerequisite: a Withings app (https://developer.withings.com/) with its callback URL
registered exactly as `http://localhost:8722/callback`.
"""
from __future__ import annotations

import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from coach.config import settings
from coach.db import init_db
from coach.integrations.withings import AUTHORIZE_URL, exchange_code, save_tokens

PORT = 8722
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPE = "user.metrics"

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
        msg = "Withings authorized. You can close this tab." if _code else "Authorization failed."
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *args):  # silence default logging
        pass


def main() -> None:
    if not settings.withings_client_id or not settings.withings_client_secret:
        raise SystemExit("Set WITHINGS_CLIENT_ID and WITHINGS_CLIENT_SECRET in .env first.")

    init_db()

    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.withings_client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "state": secrets.token_urlsafe(16),
        }
    )
    print(f"Opening browser to authorize Withings...\nIf it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", PORT), _Handler)
    while _code is None:
        server.handle_request()

    body = exchange_code(_code, REDIRECT_URI)
    expires_at = int(time.time()) + int(body["expires_in"])
    save_tokens(body["access_token"], body["refresh_token"], expires_at)
    print("Withings authorized. Tokens saved.")
    print("Now run `coach-sync` to pull your body measurements.")


if __name__ == "__main__":
    main()
