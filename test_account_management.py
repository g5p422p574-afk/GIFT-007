from datetime import timedelta

import pytest
from flask import Flask
from werkzeug.security import check_password_hash, generate_password_hash

from csrf import csrf_protect
from models import db, Store, User
from routes.home import home_bp
from routes.orders import orders_bp
from routes.products import products_bp


@pytest.fixture()
def app(monkeypatch):
    test_app = Flask(__name__, template_folder="templates", static_folder="static")
    test_app.config.update(
        SECRET_KEY="test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        UPLOAD_FOLDER="uploads",
    )
    db.init_app(test_app)
    csrf_protect(test_app)
    test_app.register_blueprint(home_bp)
    test_app.register_blueprint(orders_bp, url_prefix="/orders")
    test_app.register_blueprint(products_bp, url_prefix="/admin")

    @test_app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return filename

    @test_app.template_filter("cst")
    def cst_filter(value, fmt="%m-%d %H:%M"):
        return (value + timedelta(hours=8)).strftime(fmt) if value else ""

    monkeypatch.setattr("routes.products.audit.log", lambda *args, **kwargs: None)

    with test_app.app_context():
        db.create_all()
        admin = User(
            store_name="管理员", phone="admin",
            password_hash=generate_password_hash("admin-password"), is_admin=True,
        )
        target = User(
            store_name="旧店名", phone="13800000001",
            password_hash=generate_password_hash("old-password"), is_admin=False,
        )
        other = User(
            store_name="其他店", phone="13800000002",
            password_hash=generate_password_hash("other-password"), is_admin=False,
        )
        db.session.add_all([admin, target, other])
        db.session.flush()
        db.session.add_all([
            Store(user_id=target.id, store_name="深圳福田店"),
            Store(user_id=target.id, store_name="深圳南山店"),
            Store(user_id=other.id, store_name="广州天河店"),
        ])
        db.session.commit()
        test_app.config["IDS"] = {
            "admin": admin.id, "target": target.id, "other": other.id,
        }
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_id"] = app.config["IDS"]["admin"]
        sess["is_admin"] = True
        sess["_csrf_token"] = "token"
    return client


def test_accounts_can_be_searched_by_store_name(app, client):
    response = client.get("/admin/accounts?q=福田")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "账号管理" in html
    assert "深圳福田店" in html
    assert "深圳南山店" in html
    assert "13800000001" in html
    assert "13800000002" not in html

    legacy_name_response = client.get("/admin/accounts?q=旧店名")
    assert "13800000001" not in legacy_name_response.get_data(as_text=True)


def test_admin_can_reset_password_without_old_password(app, client):
    target_id = app.config["IDS"]["target"]
    response = client.post(
        f"/admin/account/{target_id}/reset-password",
        data={
            "csrf_token": "token",
            "new_password": "new-password-123",
            "confirm_password": "new-password-123",
            "q": "福田",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "密码已重置" in response.get_data(as_text=True)
    with app.app_context():
        target = db.session.get(User, target_id)
        assert check_password_hash(target.password_hash, "new-password-123")


def test_mismatched_password_is_rejected(app, client):
    target_id = app.config["IDS"]["target"]
    with app.app_context():
        old_hash = db.session.get(User, target_id).password_hash
    response = client.post(
        f"/admin/account/{target_id}/reset-password",
        data={
            "csrf_token": "token",
            "new_password": "new-password-123",
            "confirm_password": "different-password",
        },
        follow_redirects=True,
    )
    assert "两次输入的新密码不一致" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(User, target_id).password_hash == old_hash


def test_admin_account_cannot_be_reset(app, client):
    admin_id = app.config["IDS"]["admin"]
    response = client.post(
        f"/admin/account/{admin_id}/reset-password",
        data={
            "csrf_token": "token",
            "new_password": "new-password-123",
            "confirm_password": "new-password-123",
        },
    )
    assert response.status_code == 404
