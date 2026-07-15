import os
from datetime import timedelta
from werkzeug.security import generate_password_hash
from flask import Flask, send_from_directory
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from config import ENV, SECRET_KEY, SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS, UPLOAD_FOLDER, BASE_DIR
from models import db, User, Store, Order, Address, InventorySync
from csrf import csrf_protect

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,   # test connection before use — catches stale connections
    "pool_recycle": 3600,    # recycle connections older than 1 hour
}

csrf_protect(app)


# Jinja2 filter: convert UTC datetime to CST (UTC+8) for display
@app.template_filter("cst")
def _cst_filter(dt, fmt="%m-%d %H:%M"):
    if dt is None:
        return ""
    from datetime import timedelta
    return (dt + timedelta(hours=8)).strftime(fmt)


db.init_app(app)

# SQLite does not enforce foreign keys by default — turn them on per connection.
if ENV == "development":
    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # NOTE: This route serves all uploads (product images, payment proofs,
    # shipping labels) without authentication because product images appear
    # on the public home page.  UUID filenames (128-bit entropy) make
    # enumeration infeasible.  The order detail / print routes now enforce
    # store-level access control so filenames cannot be leaked via IDOR.
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/sw.js")
def service_worker():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "sw.js",
        mimetype="application/javascript",
    )


@app.route("/offline.html")
def offline():
    return send_from_directory(os.path.join(app.root_path, "static"), "offline.html")


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

    # ── Migration: create Store for each existing User that has no Store yet ──
    # Also handles adding store_id / sku columns to existing tables on upgrade.
    try:
        inspector = inspect(db.engine)

        # Ensure sku column exists on 'product' table
        product_cols = [c["name"] for c in inspector.get_columns("product")]
        if "sku" not in product_cols:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE product ADD COLUMN sku VARCHAR(100) DEFAULT ''"))
            print("  [Migration] Added sku column to product table.")

        # Ensure store_id column exists on 'order' table (for upgrades from old schema)
        order_cols = [c["name"] for c in inspector.get_columns("order")]
        if "store_id" not in order_cols:
            # MySQL compatible: use backtick quoting for reserved word "order"
            quote = "`" if ENV == "production" else '"'
            with db.engine.connect() as conn:
                conn.execute(text(
                    f"ALTER TABLE {quote}order{quote} ADD COLUMN store_id INTEGER"
                ))
            print("  [Migration] Added store_id column to order table.")

        # Ensure store_id column exists on 'address' table
        addr_cols = [c["name"] for c in inspector.get_columns("address")]
        if "store_id" not in addr_cols:
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE address ADD COLUMN store_id INTEGER"
                ))
            print("  [Migration] Added store_id column to address table.")

        # Ensure inventory_sync table exists
        if "inventory_sync" not in inspector.get_table_names():
            db.create_all()  # creates any missing tables, including inventory_sync
            print("  [Migration] Created inventory_sync table.")

        # Migrate data: create Store for each non-admin User without one
        users_without_store = User.query.filter(
            User.is_admin == False,
            ~User.stores.any()
        ).all()
        if users_without_store:
            for u in users_without_store:
                store = Store(user_id=u.id, store_name=u.store_name)
                db.session.add(store)
                db.session.flush()  # get store.id
                # Migrate addresses belonging to this user
                Address.query.filter_by(user_id=u.id).filter(
                    (Address.store_id == None) | (Address.store_id == 0)
                ).update({"store_id": store.id}, synchronize_session=False)
                # Migrate orders belonging to this user
                Order.query.filter_by(user_id=u.id).filter(
                    (Order.store_id == None) | (Order.store_id == 0)
                ).update({"store_id": store.id}, synchronize_session=False)
                db.session.commit()  # commit per user to avoid large transactions
            print(f"  [Migration] Created stores for {len(users_without_store)} existing users.")
    except Exception as e:
        db.session.rollback()
        import traceback
        print(f"  [Migration] Skipped (this is normal on fresh install): {e}")
        traceback.print_exc()

    # Create default admin if not exists
    if not User.query.filter_by(is_admin=True).first():
        admin = User(
            store_name="管理员",
            phone="admin",
            password_hash=generate_password_hash(os.environ.get("GIFT_ADMIN_PASSWORD", "REMOVED_ADMIN_PASSWORD"), method="pbkdf2:sha256"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

if __name__ == "__main__":
    env_label = "PRODUCTION" if ENV == "production" else "DEVELOPMENT"
    print(f"\n  GIFT_ENV = {env_label}")
    print(f"  DB       = {app.config['SQLALCHEMY_DATABASE_URI']}\n")
    app.run(debug=(ENV == "development"), host="0.0.0.0", port=5000)
