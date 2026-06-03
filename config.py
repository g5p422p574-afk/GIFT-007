import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ── Environment ──────────────────────────────────────────────────────────
# Set GIFT_ENV=production to use the remote MySQL database.
# Default is "development" → local SQLite, safe for testing.
ENV = os.environ.get("GIFT_ENV", "development").lower()
if ENV not in ("development", "production"):
    sys.exit(f"Invalid GIFT_ENV '{ENV}'. Must be 'development' or 'production'.")

# ── Secret ──────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get(
    "GIFT_SECRET_KEY",
    "gift-app-secret-key" if ENV == "development" else "change-me-in-production"
)

# ── Database ─────────────────────────────────────────────────────────────
if ENV == "development":
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'gift.db')}"
else:
    SQLALCHEMY_DATABASE_URI = (
        "mysql+pymysql://root:REMOVED_DB_PASSWORD_ENCODED"
        "@rm-uf6d744cennmvjx1pyo.mysql.rds.aliyuncs.com:3306"
        "/srdz_888?charset=utf8mb4"
    )

SQLALCHEMY_TRACK_MODIFICATIONS = False

# ── Uploads ──────────────────────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
