from datetime import datetime
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, current_app
from models import db, Order, OrderItem
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


@orders_bp.route("/")
def list_orders():
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    orders = Order.query
    if q:
        orders = orders.filter(
            Order.customer_name.contains(q)
            | Order.customer_address.contains(q)
            | Order.tracking_no.contains(q)
            | Order.items.any(OrderItem.product.has(name=q))
        )
    if date_from:
        orders = orders.filter(Order.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        orders = orders.filter(Order.created_at <= datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))

    orders = orders.order_by(Order.created_at.desc()).all()
    return render_template("order_list.html", orders=orders, q=q, date_from=date_from, date_to=date_to)


@orders_bp.route("/<int:order_id>")
def detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("order_detail.html", order=order)


@orders_bp.route("/<int:order_id>/ship", methods=["POST"])
def ship(order_id):
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
    return redirect(url_for("orders.detail", order_id=order.id))


@orders_bp.route("/<int:order_id>/print")
def print_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("order_print.html", order=order)


@orders_bp.route("/batch-print")
def batch_print():
    ids = request.args.get("ids", "")
    if not ids:
        return redirect(url_for("orders.list_orders"))
    id_list = [int(i) for i in ids.split(",") if i.strip().isdigit()]
    orders = Order.query.filter(Order.id.in_(id_list)).order_by(Order.created_at.desc()).all()
    return render_template("order_batch_print.html", orders=orders)
