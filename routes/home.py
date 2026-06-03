import os
import re
import uuid
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from models import db, Product, User, Store, Order, OrderItem, Address
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


def get_current_store():
    """Return the Store for the current session, or None.
    Handles old sessions that have user_id but no store_id yet."""
    if "store_id" in session:
        store = Store.query.get(session["store_id"])
        if store:
            return store
    # Recover: old session or store_id points to deleted store
    if "user_id" in session:
        first_store = Store.query.filter_by(user_id=session["user_id"]).first()
        if first_store:
            session["store_id"] = first_store.id
            return first_store
    return None


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
    is_admin = session.get("is_admin", False)
    # If admin logged in, get admin user for display
    if not user and is_admin and "admin_id" in session:
        user = User.query.get(session["admin_id"])
    kwargs.setdefault("cart_count", get_cart_data()[2])
    kwargs["session_user"] = user
    kwargs["is_admin"] = is_admin
    # Current store for client nav display & store management
    if not is_admin:
        kwargs["session_store"] = get_current_store()
    # Unviewed orders count for admin notification dot
    if is_admin:
        kwargs["unviewed_count"] = Order.query.filter_by(is_viewed=False).count()
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
    store = get_current_store()
    if not store:
        return redirect(url_for("home.store_manage"))
    store_id = store.id
    if request.method == "POST":
        items, total, _ = get_cart_data()
        if not items:
            return redirect(url_for("home.cart"))

        customer_name = request.form.get("customer_name", "").strip()
        customer_phone = request.form.get("customer_phone", "").strip()
        customer_address = request.form.get("customer_address", "").strip()
        if not customer_name or not customer_phone or not customer_address:
            addresses = Address.query.filter_by(store_id=store_id).order_by(
                Address.is_default.desc(), Address.id.desc()
            ).all()
            return render_template(
                "checkout.html", items=items, total=total,
                error="请填写姓名、电话和收货地址", addresses=addresses, **template_context()
            )

        payment_image = save_upload(request.files.get("payment_image"))

        order = Order(
            store_id=store_id,
            user_id=session["user_id"],
            customer_name=customer_name,
            customer_phone=customer_phone,
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
    addresses = Address.query.filter_by(store_id=store_id).order_by(
        Address.is_default.desc(), Address.id.desc()
    ).all()
    return render_template("checkout.html", items=items, total=total, error=None, addresses=addresses, **template_context())


@home_bp.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(phone=phone, is_admin=True).first()
        if user and check_password_hash(user.password_hash, password):
            session["admin_id"] = user.id
            session["is_admin"] = True
            session.pop("user_id", None)  # clear client login
            session.pop("store_id", None)
            return redirect(url_for("products.index"))
        return render_template("login.html", error="管理员账号或密码错误", is_admin=True)

    return render_template("login.html", error=None, is_admin=True)


@home_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(phone=phone, is_admin=False).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session.pop("is_admin", None)
            session.pop("admin_id", None)
            # Auto-select first store; create one if user has none
            first_store = Store.query.filter_by(user_id=user.id).first()
            if not first_store:
                first_store = Store(user_id=user.id, store_name=user.store_name)
                db.session.add(first_store)
                db.session.commit()
            session["store_id"] = first_store.id
            return redirect(request.args.get("next") or url_for("home.index"))
        return render_template("login.html", error="手机号或密码错误")

    return render_template("login.html", error=None)


@home_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        store_name = request.form.get("store_name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        password2 = request.form.get("password2", "").strip()

        if not store_name or not phone or not password or not password2:
            return render_template("register.html", error="所有字段都是必填的")

        if not re.match(r"^\d{11}$", phone):
            return render_template("register.html", error="手机号必须是11位数字")

        if password != password2:
            return render_template("register.html", error="两次输入的密码不一致")

        if len(password) < 6:
            return render_template("register.html", error="密码至少6位")

        if User.query.filter_by(phone=phone).first():
            return render_template("register.html", error="该手机号已注册")

        user = User(
            store_name=store_name,
            phone=phone,
            password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
        )
        db.session.add(user)
        db.session.flush()  # get user.id

        # Create the default store from the registered store_name
        store = Store(user_id=user.id, store_name=store_name)
        db.session.add(store)
        db.session.commit()

        session["user_id"] = user.id
        session["store_id"] = store.id
        session.pop("is_admin", None)
        session.pop("admin_id", None)
        return redirect(url_for("home.index"))

    return render_template("register.html", error=None)


# ══════════════════════════════════════════════════════════════════
# Store Management (multi-store support)
# ══════════════════════════════════════════════════════════════════

@home_bp.route("/store/manage", methods=["GET", "POST"])
@login_required
def store_manage():
    """Manage stores: list, add, edit, delete, switch."""
    user_id = session["user_id"]
    stores = Store.query.filter_by(user_id=user_id).order_by(Store.created_at.asc()).all()
    current_store = get_current_store()
    error = None
    success = None

    if request.method == "POST":
        action = request.form.get("action", "")
        store_name = request.form.get("store_name", "").strip()

        if action == "add":
            if not store_name:
                error = "门店名称不能为空"
            else:
                new_store = Store(user_id=user_id, store_name=store_name)
                db.session.add(new_store)
                db.session.commit()
                session["store_id"] = new_store.id
                success = f"门店「{store_name}」已添加并切换"
                stores = Store.query.filter_by(user_id=user_id).order_by(Store.created_at.asc()).all()

        elif action == "edit":
            store_id = request.form.get("store_id", "").strip()
            if not store_name:
                error = "门店名称不能为空"
            elif store_id:
                store = Store.query.get(int(store_id))
                if store and store.user_id == user_id:
                    store.store_name = store_name
                    db.session.commit()
                    success = f"门店名称已更新为「{store_name}」"
                    stores = Store.query.filter_by(user_id=user_id).order_by(Store.created_at.asc()).all()

        elif action == "delete":
            store_id = request.form.get("store_id", "").strip()
            if store_id:
                store = Store.query.get(int(store_id))
                if store and store.user_id == user_id:
                    # Prevent deleting the last store
                    if len(stores) <= 1:
                        error = "至少保留一个门店，无法删除"
                    # Prevent deleting store with orders
                    elif Order.query.filter_by(store_id=store.id).first():
                        error = "该门店已有订单，无法删除"
                    else:
                        store_name_deleted = store.store_name
                        # Delete addresses belonging to this store
                        Address.query.filter_by(store_id=store.id).delete()
                        db.session.delete(store)
                        db.session.commit()
                        # If current store was deleted, switch to another
                        if current_store and current_store.id == store.id:
                            next_store = Store.query.filter_by(user_id=user_id).first()
                            session["store_id"] = next_store.id if next_store else None
                        success = f"门店「{store_name_deleted}」已删除"
                        stores = Store.query.filter_by(user_id=user_id).order_by(Store.created_at.asc()).all()

    return render_template(
        "store_manage.html",
        stores=stores,
        current_store=current_store,
        error=error,
        success=success,
        **template_context()
    )


@home_bp.route("/store/<int:store_id>/switch")
@login_required
def store_switch(store_id):
    """Switch the active store."""
    store = Store.query.get_or_404(store_id)
    if store.user_id != session["user_id"]:
        return redirect(url_for("home.index"))
    session["store_id"] = store.id
    # Clear cart when switching stores (cart is store-scoped conceptually)
    return redirect(url_for("home.index"))


# ══════════════════════════════════════════════════════════════════
# Profile & Account
# ══════════════════════════════════════════════════════════════════

@home_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = User.query.get(session["user_id"])
    store = get_current_store()
    addresses = Address.query.filter_by(store_id=store.id).order_by(
        Address.is_default.desc(), Address.id.desc()
    ).all() if store else []
    error = None
    success = None

    if request.method == "POST":
        form_type = request.form.get("form_type", "account")

        if form_type == "store_name":
            # Update current store's name
            new_store_name = request.form.get("store_name", "").strip()
            if not new_store_name:
                error = "店名不能为空"
            elif store:
                store.store_name = new_store_name
                db.session.commit()
                success = "店名已更新"

        elif form_type == "account":
            phone = request.form.get("phone", "").strip()
            current_password = request.form.get("current_password", "").strip()
            new_password = request.form.get("new_password", "").strip()
            new_password2 = request.form.get("new_password2", "").strip()

            if phone:
                if not re.match(r"^\d{11}$", phone):
                    error = "手机号必须是11位数字"
                elif phone != user.phone:
                    existing = User.query.filter_by(phone=phone).first()
                    if existing and existing.id != user.id:
                        error = "该手机号已被其他账号使用"
                    else:
                        user.phone = phone
                        success = "手机号已更新"

            if (current_password or new_password or new_password2) and not error:
                if not current_password:
                    error = "请输入当前密码"
                elif not check_password_hash(user.password_hash, current_password):
                    error = "当前密码不正确"
                elif not new_password:
                    error = "请输入新密码"
                elif len(new_password) < 6:
                    error = "新密码至少6位"
                elif new_password != new_password2:
                    error = "两次输入的新密码不一致"
                else:
                    user.password_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
                    success = success or "密码已更新"

            if not error and not success:
                success = "保存成功"
            if not error:
                db.session.commit()

    return render_template(
        "profile.html",
        user=user,
        store=store,
        addresses=addresses,
        error=error,
        success=success,
        **template_context()
    )


# ══════════════════════════════════════════════════════════════════
# Address Management (scoped to current store)
# ══════════════════════════════════════════════════════════════════

@home_bp.route("/profile/address/add", methods=["POST"])
@login_required
def address_add():
    store = get_current_store()
    if not store:
        return redirect(url_for("home.store_manage"))
    store_id = store.id
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    address_text = request.form.get("address", "").strip()
    if not name or not phone or not address_text:
        return redirect(url_for("home.profile", _anchor="addresses"))
    addr = Address(store_id=store_id, user_id=session["user_id"], name=name, phone=phone, address=address_text)
    db.session.add(addr)
    existing = Address.query.filter_by(store_id=store_id).first()
    if existing is None:
        addr.is_default = True
    db.session.commit()
    return redirect(url_for("home.profile", _anchor="addresses"))


@home_bp.route("/profile/address/<int:addr_id>/edit", methods=["POST"])
@login_required
def address_edit(addr_id):
    store = get_current_store()
    if not store:
        return redirect(url_for("home.store_manage"))
    addr = Address.query.get_or_404(addr_id)
    if addr.store_id != store.id:
        return redirect(url_for("home.profile"))
    addr.name = request.form.get("name", "").strip()
    addr.phone = request.form.get("phone", "").strip()
    addr.address = request.form.get("address", "").strip()
    if not addr.name or not addr.phone or not addr.address:
        return redirect(url_for("home.profile", _anchor="addresses"))
    db.session.commit()
    return redirect(url_for("home.profile", _anchor="addresses"))


@home_bp.route("/profile/address/<int:addr_id>/delete", methods=["POST"])
@login_required
def address_delete(addr_id):
    store = get_current_store()
    if not store:
        return redirect(url_for("home.store_manage"))
    addr = Address.query.get_or_404(addr_id)
    if addr.store_id != store.id:
        return redirect(url_for("home.profile"))
    was_default = addr.is_default
    db.session.delete(addr)
    if was_default:
        remaining = Address.query.filter_by(store_id=store.id).first()
        if remaining:
            remaining.is_default = True
    db.session.commit()
    return redirect(url_for("home.profile", _anchor="addresses"))


@home_bp.route("/profile/address/<int:addr_id>/default", methods=["POST"])
@login_required
def address_set_default(addr_id):
    store = get_current_store()
    if not store:
        return redirect(url_for("home.store_manage"))
    addr = Address.query.get_or_404(addr_id)
    if addr.store_id != store.id:
        return redirect(url_for("home.profile"))
    Address.query.filter_by(store_id=store.id).update({"is_default": False})
    addr.is_default = True
    db.session.commit()
    return redirect(url_for("home.profile", _anchor="addresses"))


# ══════════════════════════════════════════════════════════════════
# Logout
# ══════════════════════════════════════════════════════════════════

@home_bp.route("/logout")
def logout():
    was_admin = session.get("is_admin", False)
    session.clear()
    if was_admin:
        return redirect(url_for("home.admin_login"))
    return redirect(url_for("home.index"))
