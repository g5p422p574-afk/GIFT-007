import pytest
from flask import Flask

from csrf import csrf_protect
from models import db, Order, OrderItem, Product, Store, User
from routes.home import home_bp
from routes.orders import orders_bp


@pytest.fixture()
def app():
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

    @test_app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return filename

    with test_app.app_context():
        db.create_all()
        user = User(store_name="测试店", phone="13800000000", password_hash="x")
        db.session.add(user)
        db.session.flush()
        store = Store(user_id=user.id, store_name="测试店")
        company = Product(name="公司商品", shelf_no="A1", sku="SKU-1", price=10)
        factory = Product(name="厂家商品", shelf_no="B1", sku="", price=20)
        company_two = Product(name="公司商品二", shelf_no="A2", sku=" SKU-2 ", price=30)
        db.session.add_all([store, company, factory, company_two])
        db.session.commit()
        test_app.config["IDS"] = {
            "user": user.id,
            "store": store.id,
            "company": company.id,
            "factory": factory.id,
            "company_two": company_two.id,
        }
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    client = app.test_client()
    ids = app.config["IDS"]
    with client.session_transaction() as sess:
        sess["user_id"] = ids["user"]
        sess["store_id"] = ids["store"]
        sess["_csrf_token"] = "token"
    return client


def add(client, product_id):
    return client.post(
        f"/cart/add/{product_id}",
        headers={"X-CSRF-Token": "token", "X-Requested-With": "XMLHttpRequest"},
    )


def test_labels_and_same_delivery_products_can_share_cart(app, client):
    ids = app.config["IDS"]
    page = client.get("/")
    assert "公司直发" in page.get_data(as_text=True)
    assert "厂家直发" in page.get_data(as_text=True)
    assert add(client, ids["company"]).status_code == 200
    assert add(client, ids["company_two"]).status_code == 200


@pytest.mark.parametrize("first,second", [("company", "factory"), ("factory", "company")])
def test_mixed_delivery_is_rejected_with_exact_message(app, client, first, second):
    ids = app.config["IDS"]
    assert add(client, ids[first]).status_code == 200
    response = add(client, ids[second])
    assert response.status_code == 409
    assert response.get_json()["message"] == "厂家直发和公司直发商品不允许同时加入购物车下单，请先清空购物车"
    with client.session_transaction() as sess:
        assert str(ids[second]) not in sess["cart"]


def test_legacy_mixed_cart_cannot_checkout(app, client):
    ids = app.config["IDS"]
    with client.session_transaction() as sess:
        sess["cart"] = {str(ids["company"]): 1, str(ids["factory"]): 1}
    response = client.get("/order/create", follow_redirects=True)
    assert response.request.path == "/cart"
    assert "厂家直发和公司直发商品不允许同时加入购物车下单，请先清空购物车" in response.get_data(as_text=True)


def test_reorder_cannot_mix_with_existing_cart(app, client):
    ids = app.config["IDS"]
    with app.app_context():
        order = Order(
            store_id=ids["store"], user_id=ids["user"], customer_name="张三",
            customer_address="测试地址", total_amount=20,
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=ids["factory"], quantity=2, unit_price=20))
        db.session.commit()
        order_id = order.id
    with client.session_transaction() as sess:
        sess["cart"] = {str(ids["company"]): 1}
    response = client.post(
        f"/orders/{order_id}/reorder", data={"csrf_token": "token"},
        follow_redirects=True,
    )
    assert "厂家直发和公司直发商品不允许同时加入购物车下单，请先清空购物车" in response.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert sess["cart"] == {str(ids["company"]): 1}
