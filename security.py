"""Security audit logging and attack detection.

Logs security-relevant events to a rotating JSON-lines file and maintains
in-memory counters for real-time detection of suspicious patterns.

Events tracked:
  - login_failed / login_success
  - csrf_failure
  - order_404_burst        (5+ order 404s from same IP in 60s)
  - csrf_attack_suspected  (3+ CSRF failures from same IP in 60s)
  - brute_force_suspected  (5+ failed logins from same IP in 60s)
  - unauthorized_access    (store_id mismatch -> 404)

Usage:
    from security import audit

    audit.log("login_failed", ip="1.2.3.4", detail="wrong password")
    suspicious = audit.detect("csrf_failure", ip="1.2.3.4")
"""

import json
import os
import time
import threading
from collections import defaultdict

from flask import request


def get_real_ip():
    """Return the client's real IP, respecting Nginx reverse-proxy headers.

    Checks X-Real-IP first (set by nginx: proxy_set_header X-Real-IP $remote_addr),
    then X-Forwarded-For, falling back to request.remote_addr.
    """
    # X-Real-IP is set to the single client IP by Nginx — preferred.
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    # X-Forwarded-For can be a comma-separated list; take the first (original client).
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "security.log")
MAX_LOG_SIZE = 512 * 1024  # 512 KB — rotate when exceeded

# ── In-memory burst detectors ──────────────────────────────────────
# key: (event_type, ip) → list of timestamps (within 60s window)

_lock = threading.Lock()
_counters = defaultdict(list)

# Thresholds: (max_count, window_seconds, alert_event_type)
DETECTION_RULES = {
    "order_404":        (5, 60, "order_enumeration_probe"),
    "csrf_failure":     (3, 60, "csrf_attack_suspected"),
    "login_failed":     (5, 60, "brute_force_suspected"),
    "unauthorized_access": (3, 60, "unauthorized_access_burst"),
}


class AuditLog:
    """Thread-safe JSON-lines audit log with burst detection."""

    def __init__(self):
        self._write_lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────────

    def log(self, event_type, ip="", user_agent="", user_id=None, detail=""):
        """Record an event and return a detection alert if triggered."""
        entry = {
            "ts": time.time(),
            "type": event_type,
            "ip": ip or "-",
            "ua": user_agent or "-",
            "uid": user_id,
            "detail": detail,
        }
        self._write(entry)
        return self._detect(event_type, ip)

    def detect(self, event_type, ip):
        """Check if a given (event_type, ip) crosses a detection threshold."""
        return self._detect(event_type, ip)

    def get_recent(self, limit=200):
        """Return the most recent log entries (for admin dashboard)."""
        entries = []
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for line in lines[-limit:]:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            entries.reverse()
        except FileNotFoundError:
            pass
        return entries

    def stats(self):
        """Return summary stats for the admin dashboard."""
        entries = self.get_recent(500)
        now = time.time()
        day_ago = now - 86400

        types = defaultdict(int)
        ips = set()
        alerts_today = []

        for e in entries:
            types[e["type"]] += 1
            if e["ip"] and e["ip"] != "-":
                ips.add(e["ip"])
            if e["ts"] >= day_ago and "probe" in e.get("type", "") or "attack" in e.get("type", "") or "burst" in e.get("type", "") or "suspected" in e.get("type", ""):
                alerts_today.append(e)

        return {
            "total_events": len(entries),
            "unique_ips": len(ips),
            "by_type": dict(types),
            "alerts_24h": alerts_today[:50],
        }

    # ── Internals ───────────────────────────────────────────────────

    def _write(self, entry):
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._write_lock:
            # Rotate if too large
            try:
                if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_SIZE:
                    bak = LOG_PATH + ".old"
                    if os.path.exists(bak):
                        os.remove(bak)
                    os.rename(LOG_PATH, bak)
            except OSError:
                pass
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)

    def _detect(self, event_type, ip):
        """Update in-memory counter; return alert dict if threshold crossed."""
        if event_type not in DETECTION_RULES:
            return None

        threshold, window, alert_type = DETECTION_RULES[event_type]
        now = time.time()
        key = (event_type, ip)

        with _lock:
            _counters[key] = [t for t in _counters[key] if now - t < window]
            _counters[key].append(now)
            count = len(_counters[key])

            # Cleanup stale keys periodically
            if len(_counters) > 5000:
                stale = [k for k in _counters if not _counters[k]]
                for k in stale:
                    del _counters[k]

        if count >= threshold:
            alert = {
                "ts": now,
                "type": alert_type,
                "ip": ip,
                "detail": f"{count} occurrences in {window}s",
            }
            self._write(alert)
            return alert
        return None


# Singleton
audit = AuditLog()
