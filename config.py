import os
import sys
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ── Environment ──────────────────────────────────────────────────────────
ENV = os.environ.get("GIFT_ENV", "development").lower()
if ENV not in ("development", "production"):
    sys.exit(f"Invalid GIFT_ENV '{ENV}'. Must be 'development' or 'production'.")

# ── Secret ──────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("GIFT_SECRET_KEY")
if not SECRET_KEY:
    if ENV == "development":
        SECRET_KEY = "gift-app-secret-key"
    else:
        # Auto-generate a strong secret key on first run.
        # Caveat: on multi-worker restart, each worker generates a different key,
        # invalidating existing sessions. Set GIFT_SECRET_KEY explicitly for production.
        SECRET_KEY = secrets.token_hex(32)

# ── Database ─────────────────────────────────────────────────────────────
if ENV == "development":
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'gift.db')}"
else:
    db_host = os.environ.get("GIFT_DB_HOST", "rm-uf6d744cennmvjx1pyo.mysql.rds.aliyuncs.com")
    db_port = os.environ.get("GIFT_DB_PORT", "3306")
    db_user = os.environ.get("GIFT_DB_USER", "root")
    db_password = os.environ.get("GIFT_DB_PASSWORD", "")
    db_name = os.environ.get("GIFT_DB_NAME", "srdz_888")
    if not db_password:
        sys.exit("GIFT_DB_PASSWORD environment variable is required in production mode.")
    # URL-encode the password (handle special characters like !)
    from urllib.parse import quote_plus
    db_password_enc = quote_plus(db_password)
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{db_user}:{db_password_enc}"
        f"@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
    )

SQLALCHEMY_TRACK_MODIFICATIONS = False

# ── Uploads ──────────────────────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
