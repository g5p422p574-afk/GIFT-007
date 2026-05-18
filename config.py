import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = "gift-app-secret-key"
SQLALCHEMY_DATABASE_URI = "mysql+pymysql://root:REMOVED_DB_PASSWORD_ENCODED@rm-uf6d744cennmvjx1pyo.mysql.rds.aliyuncs.com:3306/srdz_888?charset=utf8mb4"
SQLALCHEMY_TRACK_MODIFICATIONS = False

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
