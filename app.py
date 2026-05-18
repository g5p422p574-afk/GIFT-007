import os
from werkzeug.security import generate_password_hash
from flask import Flask, send_from_directory
from config import SECRET_KEY, SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS, UPLOAD_FOLDER, BASE_DIR
from models import db, User

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db.init_app(app)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


from routes.home import home_bp
from routes.orders import orders_bp
from routes.products import products_bp

app.register_blueprint(home_bp)
app.register_blueprint(orders_bp, url_prefix="/orders")
app.register_blueprint(products_bp, url_prefix="/admin")

with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass  # tables exist, another worker created them

    # Create default admin if not exists
    if not User.query.filter_by(is_admin=True).first():
        admin = User(
            store_name="管理员",
            phone="admin",
            password_hash=generate_password_hash("REMOVED_ADMIN_PASSWORD", method="pbkdf2:sha256"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
