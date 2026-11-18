from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session, flash
from sqlalchemy import Integer, cast, func, text as _sql_text
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash
from models import db, Product, User, Store, OrderItem, Order
from image_utils import save_upload
from security import audit, get_real_ip

products_bp = Blueprint("products", __name__)


def _cst_datetime_expression(column):
    """Return a database expression converting a UTC datetime to Beijing time."""
    database_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if database_uri.startswith("sqlite"):
        return func.datetime(column, "+8 hours")
    return column + _sql_text("INTERVAL 8 HOUR")


def _cst_hour_expression(column):
    """Return the hour component of a UTC datetime after conversion to Beijing time."""
    database_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if database_uri.startswith("sqlite"):
        return cast(func.strftime("%H", column, "+8 hours"), Integer)
    return func.hour(_cst_datetime_expression(column))


def parse_stock(value):
    """Parse optional stock input; blank means unlimited inventory."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        stock = int(value)
    except ValueError:
        raise ValueError("库存必须填写非负整数")
    if stock < 0:
        raise ValueError("库存不能小于 0")
    return stock


def parse_low_stock_threshold(value):
    """Parse an optional warning threshold; blank disables warnings."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        threshold = int(value)
    except ValueError:
        raise ValueError("库存预警阈值必须填写非负整数")
    if threshold < 0:
        raise ValueError("库存预警阈值不能小于 0")
    return threshold


def low_stock_products_query():
    """Products whose finite stock has reached their configured threshold."""
    return Product.query.filter(
        Product.stock.isnot(None),
        Product.low_stock_threshold.isnot(None),
        Product.stock <= Product.low_stock_threshold,
    )


def get_admin_user():
    if session.get("admin_id"):
        return User.query.get(session["admin_id"])
    return None


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("home.admin_login"))
        return f(*args, **kwargs)
    return decorated


@products_bp.route("/")
@admin_required
def index():
    q = request.args.get("q", "").strip()
    products = Product.query
    if q:
        products = products.filter(Product.name.contains(q) | Product.shelf_no.contains(q) | Product.sku.contains(q))
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    if per_page not in (20, 50, 100):
        per_page = 20
    pagination = products.order_by(Product.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    unviewed = Order.query.filter_by(is_viewed=False).count()
    # Build base URL for pagination
    qs_parts = []
    for k, v in request.args.items():
        if k not in ("page", "per_page"):
            qs_parts.append(f"{k}={v}")
    page_url = request.path + "?" + ("&".join(qs_parts) + "&" if qs_parts else "")
    return render_template("admin_products.html", products=pagination.items, pagination=pagination,
                           unviewed_count=unviewed, session_user=get_admin_user(), q=q,
                           page_url=page_url, per_page=per_page)


@products_bp.route("/inventory-alerts")
@admin_required
def inventory_alerts():
    q = request.args.get("q", "").strip()
    products = low_stock_products_query()
    if q:
        products = products.filter(
            Product.name.contains(q)
            | Product.shelf_no.contains(q)
            | Product.sku.contains(q)
        )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    if per_page not in (20, 50, 100):
        per_page = 20
    pagination = products.order_by(
        Product.stock.asc(), Product.low_stock_threshold.desc(), Product.name.asc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    qs_parts = []
    for key, value in request.args.items():
        if key not in ("page", "per_page"):
            qs_parts.append(f"{key}={value}")
    page_url = request.path + "?" + ("&".join(qs_parts) + "&" if qs_parts else "")
    return render_template(
        "inventory_alerts.html",
        products=pagination.items,
        pagination=pagination,
        q=q,
        page_url=page_url,
        per_page=per_page,
        unviewed_count=Order.query.filter_by(is_viewed=False).count(),
        session_user=get_admin_user(),
    )


@products_bp.route("/product/add", methods=["GET", "POST"])
@admin_required
def add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        shelf_no = request.form.get("shelf_no", "").strip()
        sku = request.form.get("sku", "").strip()
        price = request.form.get("price", "").strip()
        if not name or not shelf_no or not price:
            return render_template("product_form.html", product=None, error="请填写完整信息", unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())
        # SKU uniqueness check (skip empty)
        if sku and Product.query.filter(Product.sku == sku).first():
            return render_template("product_form.html", product=None, error=f"SKU '{sku}' 已存在，请使用唯一编码", unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())
        try:
            stock = parse_stock(request.form.get("stock"))
            low_stock_threshold = parse_low_stock_threshold(
                request.form.get("low_stock_threshold")
            )
        except ValueError as e:
            return render_template("product_form.html", product=None, error=str(e), unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())
        image = save_upload(
            request.files.get("image"), current_app.config["UPLOAD_FOLDER"]
        )
        product = Product(
            name=name, shelf_no=shelf_no, sku=sku, price=float(price),
            stock=stock, low_stock_threshold=low_stock_threshold, image=image,
        )
        db.session.add(product)
        db.session.commit()
        return redirect(url_for("products.index"))
    return render_template("product_form.html", product=None, error=None, unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())


@products_bp.route("/product/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        product.name = request.form.get("name", "").strip()
        product.shelf_no = request.form.get("shelf_no", "").strip()
        sku = request.form.get("sku", "").strip()
        # SKU uniqueness check (skip empty, exclude self)
        if sku and Product.query.filter(Product.sku == sku, Product.id != product_id).first():
            return render_template("product_form.html", product=product, error=f"SKU '{sku}' 已被其他商品使用", unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())
        try:
            stock = parse_stock(request.form.get("stock"))
            low_stock_threshold = parse_low_stock_threshold(
                request.form.get("low_stock_threshold")
            )
        except ValueError as e:
            return render_template("product_form.html", product=product, error=str(e), unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())
        product.sku = sku
        product.price = float(request.form.get("price", "").strip())
        product.stock = stock
        product.low_stock_threshold = low_stock_threshold
        img = save_upload(
            request.files.get("image"), current_app.config["UPLOAD_FOLDER"]
        )
        if img:
            product.image = img
        db.session.commit()
        return redirect(url_for("products.index"))
    return render_template("product_form.html", product=product, error=None, unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())


@products_bp.route("/product/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete(product_id):
    product = Product.query.get_or_404(product_id)
    # Delete associated order items first to avoid FK constraint error
    OrderItem.query.filter_by(product_id=product.id).delete()
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("products.index"))


@products_bp.route("/product/<int:product_id>/toggle-stock", methods=["POST"])
@admin_required
def toggle_stock(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_out_of_stock = not product.is_out_of_stock
    db.session.commit()
    return redirect(url_for("products.index"))


@products_bp.route("/finance")
@admin_required
def finance():
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    store_q = request.args.get("store", "").strip()
    time_period = request.args.get("time_period", "").strip()
    if time_period not in ("early", "late"):
        time_period = ""

    base = Order.query.filter(Order.status.in_(["confirmed", "shipped"]))

    # Store name filter
    if store_q:
        base = base.filter(Order.store.has(Store.store_name.contains(store_q)))

    # Date range filter (CST input -> UTC query)
    if date_from:
        utc_from = datetime.strptime(date_from, "%Y-%m-%d") - timedelta(hours=8)
        base = base.filter(Order.created_at >= utc_from)
    if date_to:
        utc_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59) - timedelta(hours=8)
        base = base.filter(Order.created_at <= utc_to)

    # Allowed checkout periods are queried separately in Beijing time.
    if time_period:
        cst_hour = _cst_hour_expression(Order.created_at)
        if time_period == "early":
            base = base.filter(cst_hour < 8)
        else:
            base = base.filter(cst_hour >= 12)

    # Summary stats
    total_revenue = base.with_entities(func.sum(Order.total_amount)).scalar() or 0
    total_orders = base.count()

    # Today (in CST)
    now_cst = datetime.utcnow() + timedelta(hours=8)
    today_start = (now_cst).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    today_revenue = base.filter(Order.created_at >= today_start).with_entities(func.sum(Order.total_amount)).scalar() or 0
    today_orders = base.filter(Order.created_at >= today_start).count()

    # This month (CST)
    month_start = now_cst.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    month_revenue = base.filter(Order.created_at >= month_start).with_entities(func.sum(Order.total_amount)).scalar() or 0
    month_orders = base.filter(Order.created_at >= month_start).count()

    # This year (CST)
    year_start = now_cst.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    year_revenue = base.filter(Order.created_at >= year_start).with_entities(func.sum(Order.total_amount)).scalar() or 0
    year_orders = base.filter(Order.created_at >= year_start).count()

    # Per-store breakdown
    store_stats = base.with_entities(
        Store.store_name, func.sum(Order.total_amount), func.count(Order.id)
    ).join(Store, Order.store_id == Store.id, isouter=True).group_by(
        Store.store_name
    ).order_by(func.sum(Order.total_amount).desc()).all()

    # Daily breakdown (last 30 days, grouped by CST date)
    CST_DATE = func.date(_cst_datetime_expression(Order.created_at))
    daily_stats = base.filter(
        Order.created_at >= datetime.utcnow() - timedelta(days=31)
    ).with_entities(
        CST_DATE, func.sum(Order.total_amount), func.count(Order.id)
    ).group_by(
        CST_DATE
    ).order_by(CST_DATE.desc()).all()

    unviewed = Order.query.filter_by(is_viewed=False).count()

    return render_template(
        "finance.html",
        total_revenue=total_revenue, total_orders=total_orders,
        today_revenue=today_revenue, today_orders=today_orders,
        month_revenue=month_revenue, month_orders=month_orders,
        year_revenue=year_revenue, year_orders=year_orders,
        store_stats=store_stats, daily_stats=daily_stats,
        date_from=date_from, date_to=date_to, store_q=store_q,
        time_period=time_period,
        unviewed_count=unviewed,
        session_user=get_admin_user(),
    )


@products_bp.route("/accounts")
@admin_required
def accounts():
    """Find storefront accounts by store name and manage their passwords."""
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    if per_page not in (20, 50, 100):
        per_page = 20

    query = User.query.filter_by(is_admin=False).options(joinedload(User.stores))
    if q:
        query = query.filter(
            User.stores.any(Store.store_name.contains(q))
            | (~User.stores.any() & User.store_name.contains(q))
        )
    pagination = query.order_by(User.created_at.desc(), User.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    page_url = url_for("products.accounts", q=q) + "&"
    return render_template(
        "admin_accounts.html",
        accounts=pagination.items,
        pagination=pagination,
        q=q,
        page_url=page_url,
        per_page=per_page,
        unviewed_count=Order.query.filter_by(is_viewed=False).count(),
        session_user=get_admin_user(),
    )


@products_bp.route("/account/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_account_password(user_id):
    """Reset a storefront account password without requiring its old password."""
    user = User.query.filter_by(id=user_id, is_admin=False).first_or_404()
    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()
    q = request.form.get("q", "").strip()

    if len(new_password) < 6:
        flash("新密码至少6位", "error")
    elif len(new_password) > 128:
        flash("新密码不能超过128位", "error")
    elif new_password != confirm_password:
        flash("两次输入的新密码不一致", "error")
    else:
        user.password_hash = generate_password_hash(
            new_password, method="pbkdf2:sha256"
        )
        db.session.commit()
        audit.log(
            "admin_password_reset",
            ip=get_real_ip(),
            user_agent=request.headers.get("User-Agent", ""),
            user_id=session.get("admin_id"),
            detail=f"target_user_id={user.id} phone={user.phone}",
        )
        flash(f"账号 {user.phone} 的密码已重置", "success")

    return redirect(url_for("products.accounts", q=q))


@products_bp.route("/after-sales")
@admin_required
def after_sales():
    q = request.args.get("q", "").strip()
    base = Order.query.filter(Order.after_sale_status.in_(["pending", "processing", "done"]))
    if q:
        base = base.filter(
            Order.customer_name.contains(q)
            | Order.after_sale_reason.contains(q)
            | Order.store.has(Store.store_name.contains(q))
        )
    orders = base.options(
        joinedload(Order.items).joinedload(OrderItem.product)
    ).order_by(Order.after_sale_created_at.desc()).all()
    unviewed = Order.query.filter_by(is_viewed=False).count()
    return render_template("after_sales.html", orders=orders, q=q, unviewed_count=unviewed, session_user=get_admin_user())


@products_bp.route("/after-sale/<int:order_id>/process", methods=["POST"])
@admin_required
def process_after_sale(order_id):
    order = Order.query.get_or_404(order_id)
    action = request.form.get("action", "")
    if action == "done":
        order.after_sale_status = "done"
        order.after_sale_note = request.form.get("note", "").strip()
        order.after_sale_tracking = request.form.get("tracking", "").strip()
    elif action == "processing":
        order.after_sale_status = "processing"
    db.session.commit()
    return redirect(url_for("products.after_sales"))


@products_bp.route("/sales")
@admin_required
def sales():
    """Sales statistics: product quantities sold, grouped by date / SKU."""
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sku_q = request.args.get("sku", "").strip()

    # CST date expression
    CST_DATE = func.date(Order.created_at + _sql_text("INTERVAL 8 HOUR"))

    # Base: valid OrderItems joined with Order (for date) and Product (for SKU)
    base = (
        db.session.query(
            CST_DATE.label("order_date"),
            Product.id.label("product_id"),
            Product.name,
            Product.sku,
            Product.shelf_no,
            func.sum(OrderItem.quantity).label("total_qty"),
            func.count(func.distinct(Order.id)).label("order_count"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .join(Product, OrderItem.product_id == Product.id)
        .filter(Order.status.in_(["confirmed", "shipped"]))
    )

    if date_from:
        utc_from = datetime.strptime(date_from, "%Y-%m-%d") - timedelta(hours=8)
        base = base.filter(Order.created_at >= utc_from)
    if date_to:
        utc_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59) - timedelta(hours=8)
        base = base.filter(Order.created_at <= utc_to)
    if sku_q:
        base = base.filter(Product.sku.contains(sku_q) | Product.name.contains(sku_q))

    rows = (
        base.group_by(CST_DATE, Product.id)
        .order_by(CST_DATE.desc(), func.sum(OrderItem.quantity).desc())
        .all()
    )

    # Also compute per-SKU totals (only products that have a SKU)
    sku_base = (
        db.session.query(
            Product.id,
            Product.name,
            Product.sku,
            Product.shelf_no,
            func.sum(OrderItem.quantity).label("total_qty"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .join(Product, OrderItem.product_id == Product.id)
        .filter(Order.status.in_(["confirmed", "shipped"]))
        .filter(Product.sku != "")
        .filter(Product.sku.isnot(None))
    )
    if date_from:
        sku_base = sku_base.filter(Order.created_at >= datetime.strptime(date_from, "%Y-%m-%d") - timedelta(hours=8))
    if date_to:
        sku_base = sku_base.filter(
            Order.created_at
            <= datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59) - timedelta(hours=8)
        )
    if sku_q:
        sku_base = sku_base.filter(Product.sku.contains(sku_q) | Product.name.contains(sku_q))

    sku_totals = (
        sku_base.group_by(Product.id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .all()
    )

    sku_totals_with_flag = [
        {
            "id": r.id,
            "name": r.name,
            "sku": r.sku,
            "shelf_no": r.shelf_no,
            "total_qty": int(r.total_qty),
        }
        for r in sku_totals
    ]

    unviewed = Order.query.filter_by(is_viewed=False).count()
    return render_template(
        "admin_sales.html",
        rows=rows,
        sku_totals=sku_totals_with_flag,
        date_from=date_from,
        date_to=date_to,
        sku_q=sku_q,
        unviewed_count=unviewed,
        session_user=get_admin_user(),
    )


@products_bp.route("/security")
@admin_required
def security_dashboard():
    """Admin-only security log viewer with attack detection alerts."""
    entries = audit.get_recent(300)
    stats = audit.stats()

    # Classify events for display
    alerts = []
    info = []
    for e in entries:
        t = e.get("type", "")
        if any(kw in t for kw in ("probe", "attack", "suspected", "burst")):
            alerts.append(e)
        else:
            info.append(e)

    # Format timestamps
    def fmt_ts(ts):
        return datetime.utcfromtimestamp(ts).strftime("%m-%d %H:%M:%S")

    return render_template(
        "admin_security.html",
        alerts=alerts[:50],
        info=info[:50],
        stats=stats,
        fmt_ts=fmt_ts,
        unviewed_count=Order.query.filter_by(is_viewed=False).count(),
        session_user=get_admin_user(),
    )
