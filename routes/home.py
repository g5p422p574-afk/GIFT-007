import os
import uuid
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from models import db, Product, User, Order, OrderItem
from config import ALLOWED_EXTENSIONS

home_bp = Blueprint("home", __name__)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        fname = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], fname))
        return fname
    return ""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("home.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def get_cart_data():
    cart = session.get("cart", {})
    items = []
    total = 0
    count = 0
    for pid_str, qty in cart.items():
        product = Product.query.get(int(pid_str))
        if product:
            qty = max(1, int(qty))
            subtotal = product.price * qty
            items.append({"product": product, "quantity": qty, "subtotal": subtotal})
            total += subtotal
            count += qty
    return items, total, count


def template_context(**kwargs):
    """Add common template variables."""
    user = None
    if "user_id" in session:
        user = User.query.get(session["user_id"])
    kwargs.setdefault("cart_count", get_cart_data()[2])
    kwargs["session_user"] = user
    kwargs["is_admin"] = session.get("is_admin", False)
    return kwargs


@home_bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    products = Product.query
    if q:
        products = products.filter(
            Product.name.contains(q) | Product.shelf_no.contains(q)
        )
    products = products.order_by(Product.created_at.desc()).all()
    return render_template("home.html", products=products, q=q, **template_context())


@home_bp.route("/cart")
def cart():
    items, total, _ = get_cart_data()
    return render_template("cart.html", items=items, total=total, **template_context())


@home_bp.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    if "user_id" not in session:
        return redirect(url_for("home.login"))
    cart = session.get("cart", {})
    pid = str(product_id)
    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    return redirect(url_for("home.index"))


@home_bp.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    qty = int(request.form.get("quantity", 1))
    cart = session.get("cart", {})
    pid = str(product_id)
    if qty <= 0:
        cart.pop(pid, None)
    else:
        cart[pid] = qty
    session["cart"] = cart
    return redirect(url_for("home.cart"))


@home_bp.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    return redirect(url_for("home.cart"))


@home_bp.route("/order/create", methods=["GET", "POST"])
@login_required
def checkout():
    if request.method == "POST":
        items, total, _ = get_cart_data()
        if not items:
            return redirect(url_for("home.cart"))

        customer_name = request.form.get("customer_name", "").strip()
        customer_address = request.form.get("customer_address", "").strip()
        if not customer_name or not customer_address:
            return render_template(
                "checkout.html", items=items, total=total,
                error="请填写姓名和收货地址", **template_context()
            )

        payment_image = save_upload(request.files.get("payment_image"))

        order = Order(
            user_id=session["user_id"],
            customer_name=customer_name,
            customer_address=customer_address,
            payment_image=payment_image,
            total_amount=total,
        )
        db.session.add(order)
        db.session.flush()

        for item in items:
            oi = OrderItem(
                order_id=order.id,
                product_id=item["product"].id,
                quantity=item["quantity"],
                unit_price=item["product"].price,
            )
            db.session.add(oi)

        db.session.commit()
        session["cart"] = {}
        return redirect(url_for("orders.list_orders"))

    items, total, _ = get_cart_data()
    if not items:
        return redirect(url_for("home.cart"))
    return render_template("checkout.html", items=items, total=total, error=None, **template_context())


@home_bp.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(phone=phone, is_admin=True).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["is_admin"] = True
            return redirect(url_for("products.index"))
        return render_template("login.html", error="管理员账号或密码错误", is_admin=None, error_msg=None)

    return render_template("login.html", error=None, is_admin=True)


@home_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(phone=phone, is_admin=False).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["is_admin"] = False
            return redirect(request.args.get("next") or url_for("home.index"))
        return render_template("login.html", error="手机号或密码错误")

    return render_template("login.html", error=None)


@home_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        store_name = request.form.get("store_name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        if not store_name or not phone or not password:
            return render_template("register.html", error="所有字段都是必填的")

        if User.query.filter_by(phone=phone).first():
            return render_template("register.html", error="该手机号已注册")

        user = User(
            store_name=store_name,
            phone=phone,
            password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
        )
        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        session["is_admin"] = False
        return redirect(url_for("home.index"))

    return render_template("register.html", error=None)


@home_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home.index"))
