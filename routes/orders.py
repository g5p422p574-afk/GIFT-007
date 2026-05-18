from datetime import datetime
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from models import db, User, Order, OrderItem
from config import ALLOWED_EXTENSIONS

orders_bp = Blueprint("orders", __name__)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        fname = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], fname))
        return fname
    return ""


def is_admin_user():
    return session.get("is_admin", False)


def get_session_user():
    if "user_id" in session:
        return User.query.get(session["user_id"])
    if "admin_id" in session:
        return User.query.get(session["admin_id"])
    return None


@orders_bp.route("/")
def list_orders():
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    is_admin = request.args.get("admin") == "1" or is_admin_user()

    orders = Order.query
    # Non-admin users see only their own orders (or nothing if not logged in)
    if not is_admin_user():
        if "user_id" not in session:
            orders = orders.filter(Order.id == 0)  # show nothing
        else:
            orders = orders.filter(Order.user_id == session["user_id"])

    if q:
        # Also search by store name (via user relation)
        store_match = User.store_name.contains(q) if is_admin_user() else None
        filters = (
            Order.customer_name.contains(q)
            | Order.customer_address.contains(q)
            | Order.tracking_no.contains(q)
            | Order.items.any(OrderItem.product.has(name=q))
        )
        if store_match is not None:
            filters = filters | Order.user.has(store_match)
        orders = orders.filter(filters)
    if date_from:
        orders = orders.filter(Order.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        orders = orders.filter(Order.created_at <= datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))

    orders = orders.order_by(Order.created_at.desc()).all()

    # Admin viewing orders: mark all unviewed as viewed
    if is_admin_user():
        unviewed = [o for o in orders if not o.is_viewed]
        if unviewed:
            for o in unviewed:
                o.is_viewed = True
            db.session.commit()

    return render_template("order_list.html", orders=orders, q=q, date_from=date_from, date_to=date_to, is_admin=is_admin, session_user=get_session_user())


@orders_bp.route("/<int:order_id>")
def detail(order_id):
    is_admin = request.args.get("admin") == "1" or is_admin_user()
    order = Order.query.get_or_404(order_id)
    if is_admin_user() and not order.is_viewed:
        order.is_viewed = True
        db.session.commit()
    return render_template("order_detail.html", order=order, is_admin=is_admin, session_user=get_session_user())


@orders_bp.route("/<int:order_id>/ship", methods=["POST"])
def ship(order_id):
    if not is_admin_user():
        return redirect(url_for("home.login"))
    is_admin = request.args.get("admin") == "1" or True
    order = Order.query.get_or_404(order_id)
    tracking_no = request.form.get("tracking_no", "").strip()
    shipping_image = save_upload(request.files.get("shipping_image"))

    if tracking_no:
        order.tracking_no = tracking_no
    if shipping_image:
        order.shipping_image = shipping_image
    if tracking_no or shipping_image:
        order.status = "shipped"

    db.session.commit()
    return redirect(url_for("orders.detail", order_id=order.id, admin=1 if is_admin else None))


@orders_bp.route("/<int:order_id>/print")
def print_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("order_print.html", order=order)


@orders_bp.route("/batch-print")
def batch_print():
    if not is_admin_user():
        return redirect(url_for("home.login"))
    ids = request.args.get("ids", "")
    if not ids:
        return redirect(url_for("orders.list_orders"))
    id_list = [int(i) for i in ids.split(",") if i.strip().isdigit()]
    orders = Order.query.filter(Order.id.in_(id_list)).order_by(Order.created_at.desc()).all()
    return render_template("order_batch_print.html", orders=orders)


@orders_bp.route("/after-sales")
def my_after_sales():
    if "user_id" not in session:
        return redirect(url_for("home.login"))
    orders = Order.query.filter(
        Order.user_id == session["user_id"],
        Order.after_sale_status.in_(["pending", "processing", "done"])
    ).order_by(Order.after_sale_created_at.desc()).all()
    return render_template("client_after_sales.html", orders=orders, session_user=get_session_user())


@orders_bp.route("/<int:order_id>/after-sale", methods=["POST"])
def request_after_sale(order_id):
    if "user_id" not in session:
        return redirect(url_for("home.login"))
    order = Order.query.get_or_404(order_id)
    # Only allow client's own orders
    if order.user_id != session["user_id"]:
        return redirect(url_for("orders.list_orders"))
    # Only allow if order is shipped and no existing after-sale
    if order.status == "shipped" and not order.after_sale_status:
        order.after_sale_status = "pending"
        order.after_sale_reason = request.form.get("reason", "").strip()
        order.after_sale_created_at = datetime.utcnow()
        db.session.commit()
    return redirect(url_for("orders.detail", order_id=order.id))
