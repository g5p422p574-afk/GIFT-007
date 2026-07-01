from datetime import datetime, timedelta
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session, abort
from models import db, User, Store, Order, OrderItem
from config import ALLOWED_EXTENSIONS
from security import audit, get_real_ip

orders_bp = Blueprint("orders", __name__)


def _deny(order, reason="store_id mismatch"):
    """Log an unauthorized access attempt and abort with 404."""
    ip = get_real_ip()
    ua = request.headers.get("User-Agent", "")
    uid = session.get("user_id")
    audit.log("unauthorized_access", ip=ip, user_agent=ua, user_id=uid,
              detail=f"order_id={order.id} {reason}")
    audit.log("order_404", ip=ip, user_agent=ua, user_id=uid,
              detail=f"order_id={order.id}")
    abort(404)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# Image magic bytes for content-type validation
IMG_SIGNATURES = {
    b"\x89PNG": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF8": "gif",
    b"RIFF": "webp",
}

def is_valid_image_content(file):
    """Verify file content matches an image signature."""
    if not file:
        return False
    pos = file.tell()
    try:
        header = file.read(12)
        file.seek(pos)
        if not header:
            return False
        for sig, ext in IMG_SIGNATURES.items():
            if header.startswith(sig):
                return True
        return False
    except Exception:
        return False

def save_upload(file):
    if file and allowed_file(file.filename) and is_valid_image_content(file):
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

    orders = Order.query
    # Non-admin users see only their current store's orders
    if not is_admin_user():
        if "user_id" not in session or "store_id" not in session:
            orders = orders.filter(Order.id == 0)  # show nothing
        else:
            orders = orders.filter(Order.store_id == session["store_id"])

    if q:
        filters = (
            Order.customer_name.contains(q)
            | Order.customer_address.contains(q)
            | Order.tracking_no.contains(q)
            | Order.items.any(OrderItem.product.has(name=q))
        )
        if is_admin_user():
            filters = filters | Order.store.has(Store.store_name.contains(q))
        orders = orders.filter(filters)
    if date_from:
        # Convert user's CST date to UTC: start of day CST = previous day 16:00 UTC
        utc_from = datetime.strptime(date_from, "%Y-%m-%d") - timedelta(hours=8)
        orders = orders.filter(Order.created_at >= utc_from)
    if date_to:
        # End of day CST = same day 15:59:59 UTC
        utc_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59) - timedelta(hours=8)
        orders = orders.filter(Order.created_at <= utc_to)

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    if per_page not in (20, 50, 100):
        per_page = 20
    pagination = orders.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    orders = pagination.items

    # Admin viewing orders: mark current page unviewed as viewed
    if is_admin_user():
        unviewed = [o for o in orders if not o.is_viewed]
        if unviewed:
            for o in unviewed:
                o.is_viewed = True
            db.session.commit()

    # Build base URL for pagination (all params except page & per_page)
    page_args = {k: v for k, v in request.args.items() if k not in ("page", "per_page")}
    page_url_from = request.args.get("page", "")
    # Construct query string manually for the template
    qs_parts = []
    for k, v in page_args.items():
        qs_parts.append(f"{k}={v}")
    page_url = request.path + "?" + ("&".join(qs_parts) + "&" if qs_parts else "")
    per_page_val = per_page

    return render_template("order_list.html", orders=orders, pagination=pagination,
                           q=q, date_from=date_from, date_to=date_to,
                           is_admin=is_admin_user(), session_user=get_session_user(),
                           page_url=page_url, per_page=per_page_val)


@orders_bp.route("/<int:order_id>")
def detail(order_id):
    order = Order.query.get_or_404(order_id)
    # Non-admin users can only view their own store's orders
    if not is_admin_user():
        if "user_id" not in session or "store_id" not in session:
            return redirect(url_for("home.login"))
        if order.store_id != session["store_id"]:
            _deny(order)
    if is_admin_user() and not order.is_viewed:
        order.is_viewed = True
        db.session.commit()
    is_admin = is_admin_user()
    return render_template("order_detail.html", order=order, is_admin=is_admin, session_user=get_session_user())


@orders_bp.route("/<int:order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    if not is_admin_user():
        return redirect(url_for("home.login"))
    order = Order.query.get_or_404(order_id)
    if order.status == "ordered":
        order.status = "confirmed"
        db.session.commit()
    return redirect(request.referrer or url_for("orders.list_orders", admin=1))


@orders_bp.route("/<int:order_id>/ship", methods=["POST"])
def ship(order_id):
    if not is_admin_user():
        return redirect(url_for("home.login"))
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
    return redirect(url_for("orders.detail", order_id=order.id, admin=1))


@orders_bp.route("/<int:order_id>/payment/update", methods=["POST"])
def update_payment(order_id):
    if "user_id" not in session or "store_id" not in session:
        return redirect(url_for("home.login"))
    order = Order.query.get_or_404(order_id)
    if order.store_id != session["store_id"]:
        _deny(order)
    if order.status not in ("ordered", "confirmed"):
        return redirect(url_for("orders.detail", order_id=order.id))
    new_image = save_upload(request.files.get("payment_image"))
    if new_image:
        order.payment_image = new_image
        db.session.commit()
    return redirect(url_for("orders.detail", order_id=order.id))


@orders_bp.route("/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    if "user_id" not in session or "store_id" not in session:
        return redirect(url_for("home.login"))
    order = Order.query.get_or_404(order_id)
    if order.store_id != session["store_id"]:
        _deny(order)
    if order.status == "ordered":
        order.status = "canceled"
        db.session.commit()
    return redirect(url_for("orders.detail", order_id=order.id))


@orders_bp.route("/<int:order_id>/print")
def print_order(order_id):
    order = Order.query.get_or_404(order_id)
    # Only admin or the store that owns the order can print
    if not is_admin_user():
        if "user_id" not in session or "store_id" not in session:
            return redirect(url_for("home.login"))
        if order.store_id != session["store_id"]:
            _deny(order)
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
    if "user_id" not in session or "store_id" not in session:
        return redirect(url_for("home.login"))
    orders = Order.query.filter(
        Order.store_id == session["store_id"],
        Order.after_sale_status.in_(["pending", "processing", "done"])
    ).order_by(Order.after_sale_created_at.desc()).all()
    return render_template("client_after_sales.html", orders=orders, session_user=get_session_user())


@orders_bp.route("/<int:order_id>/after-sale", methods=["POST"])
def request_after_sale(order_id):
    if "user_id" not in session or "store_id" not in session:
        return redirect(url_for("home.login"))
    order = Order.query.get_or_404(order_id)
    # Only allow client's own store's orders
    if order.store_id != session["store_id"]:
        _deny(order)
    # Only allow if order is shipped and no existing after-sale
    if order.status == "shipped" and not order.after_sale_status:
        order.after_sale_status = "pending"
        order.after_sale_reason = request.form.get("reason", "").strip()
        order.after_sale_created_at = datetime.utcnow()
        db.session.commit()
    return redirect(url_for("orders.detail", order_id=order.id))
