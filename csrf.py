"""CSRF protection for Flask.

Generates a per-session token, injects it into template context, and
validates it on every state-changing request (POST/PUT/PATCH/DELETE).

Protected forms don't need manual changes — a JS snippet in base.html
auto-injects the token into every <form method="post"> before submit.
"""

import secrets
from flask import session, request, abort
from security import audit, get_real_ip


def generate_csrf_token():
    """Return the current CSRF token, creating one if it doesn't exist."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def csrf_protect(app):
    """Register before_request CSRF check and template context injector."""

    # Endpoints that don't need CSRF (no session, or public)
    CSRF_EXEMPT = {
        "home.login",
        "home.admin_login",
        "home.register",
        "home.index",         # GET-only but listed for clarity
        "static",
    }

    @app.before_request
    def csrf_check():
        # Safe methods — no state change
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None

        # Exempt endpoints
        if request.endpoint in CSRF_EXEMPT:
            return None

        # Service worker and offline page are always safe
        if request.endpoint in ("service_worker", "offline"):
            return None

        session_token = session.get("_csrf_token")
        if not session_token:
            audit.log("csrf_failure", ip=get_real_ip(),
                      user_agent=request.headers.get("User-Agent", ""),
                      detail="missing session token")
            abort(400)

        # Accept token via header (AJAX) or form field (traditional POST)
        request_token = request.headers.get("X-CSRF-Token") or request.form.get(
            "csrf_token"
        )
        if not request_token or not secrets.compare_digest(session_token, request_token):
            audit.log("csrf_failure", ip=get_real_ip(),
                      user_agent=request.headers.get("User-Agent", ""),
                      detail="token mismatch")
            abort(400)

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": generate_csrf_token}
