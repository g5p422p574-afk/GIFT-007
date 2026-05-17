import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from models import db, Product, Order, OrderItem
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


def get_cart_data():
    """Return list of {product, quantity, subtotal} from session cart."""
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


@home_bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    products = Product.query
    if q:
        products = products.filter(
            Product.name.contains(q) | Product.shelf_no.contains(q)
        )
    products = products.order_by(Product.created_at.desc()).all()
    _, _, cart_count = get_cart_data()
    return render_template("home.html", products=products, q=q, cart_count=cart_count)


@home_bp.route("/cart")
def cart():
    items, total, _ = get_cart_data()
    return render_template("cart.html", items=items, total=total)


@home_bp.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
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
                error="请填写姓名和收货地址"
            )

        payment_image = save_upload(request.files.get("payment_image"))

        order = Order(
            customer_name=customer_name,
            customer_address=customer_address,
            payment_image=payment_image,
            total_amount=total,
        )
        db.session.add(order)
        db.session.flush()  # get order.id

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
    return render_template("checkout.html", items=items, total=total, error=None)
