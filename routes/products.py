import os
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from sqlalchemy import func, text as _sql_text
from models import db, Product, User, Store, OrderItem, Order, InventorySync
from config import ALLOWED_EXTENSIONS
from security import audit

products_bp = Blueprint("products", __name__)


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
        image = save_upload(request.files.get("image"))
        product = Product(name=name, shelf_no=shelf_no, sku=sku, price=float(price), image=image)
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
        product.sku = request.form.get("sku", "").strip()
        product.price = float(request.form.get("price", "").strip())
        img = save_upload(request.files.get("image"))
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
    CST_DATE = func.date(Order.created_at + _sql_text("INTERVAL 8 HOUR"))
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
        unviewed_count=unviewed,
        session_user=get_admin_user(),
    )


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
    orders = base.order_by(Order.after_sale_created_at.desc()).all()
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


# ── Inventory sync config ──────────────────────────────────────────
import json as _json
try:
    from urllib.request import Request as _Request, urlopen as _urlopen
except ImportError:
    from urllib2 import Request as _Request, urlopen as _urlopen

INVENTORY_SYNC_URL = os.environ.get("GIFT_INVENTORY_SYNC_URL", "http://47.97.195.68/api/v1/sales-orders/quick")
INVENTORY_TOKEN = os.environ.get("GIFT_INVENTORY_TOKEN", "")
INVENTORY_CUSTOMER_CODE = "srdz"
INVENTORY_WAREHOUSE_CODE = "CK001"


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

    # Dates that have syncable SKU data (CST dates for picker)
    sync_dates = (
        db.session.query(CST_DATE.label("d"))
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, OrderItem.product_id == Product.id)
        .filter(Order.status.in_(["confirmed", "shipped"]))
        .filter(Product.sku != "")
        .filter(Product.sku.isnot(None))
        .group_by(CST_DATE)
        .order_by(CST_DATE.desc())
        .limit(60)
        .all()
    )
    sync_dates_list = [str(r.d) for r in sync_dates]

    # Dates already synced
    synced = {r.sync_date.isoformat(): r.synced_at for r in InventorySync.query.filter(
        InventorySync.sync_date.in_(sync_dates_list)
    ).all()}

    unviewed = Order.query.filter_by(is_viewed=False).count()
    return render_template(
        "admin_sales.html",
        rows=rows,
        sku_totals=sku_totals_with_flag,
        date_from=date_from,
        date_to=date_to,
        sku_q=sku_q,
        sync_dates=sync_dates_list,
        synced_dates=synced,
        inventory_configured=bool(INVENTORY_TOKEN),
        unviewed_count=unviewed,
        session_user=get_admin_user(),
    )


@products_bp.route("/sales/sync", methods=["POST"])
@admin_required
def sales_sync():
    """Send one day's sales to external inventory: POST /api/v1/sales-orders/quick."""
    date = request.form.get("date", "").strip()
    if not date:
        return redirect(url_for("products.sales"))

    # Check config
    if not INVENTORY_TOKEN:
        return _sales_render(
            date, date, "",
            sync_error="请先配置环境变量: GIFT_INVENTORY_TOKEN",
        )

    # Prevent duplicate sync
    from datetime import datetime as _dt
    sync_date = _dt.strptime(date, "%Y-%m-%d").date()
    existing = InventorySync.query.filter_by(sync_date=sync_date).first()
    if existing:
        return _sales_render(
            date, date, "",
            sync_error=f"{date} 已于 {existing.synced_at.strftime('%m-%d %H:%M:%S')} 同步过，每天只能同步一次",
        )

    # Query sales for the given CST date as a UTC range
    # CST day (00:00-23:59) = UTC (previous-day 16:00 to same-day 15:59)
    utc_from = datetime.strptime(date, "%Y-%m-%d") - timedelta(hours=8)
    utc_to = datetime.strptime(date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) - timedelta(hours=8)

    rows = (
        db.session.query(
            Product.sku,
            Product.name,
            Product.price,
            func.sum(OrderItem.quantity).label("total_qty"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .join(Product, OrderItem.product_id == Product.id)
        .filter(Order.status.in_(["confirmed", "shipped"]))
        .filter(Order.created_at >= utc_from)
        .filter(Order.created_at <= utc_to)
        .filter(Product.sku != "")
        .filter(Product.sku.isnot(None))
        .group_by(Product.id)
        .order_by(Product.sku)
        .all()
    )

    if not rows:
        return _sales_render(date, date, "", sync_error=f"{date} 没有可同步的 SKU 销量数据")

    # Build API payload
    items = []
    for idx, r in enumerate(rows, 1):
        items.append({
            "sku": r.sku,
            "quantity": int(r.total_qty),
            "unit_price": float(r.price),
            "line_number": idx,
        })

    payload = {
        "customer_code": INVENTORY_CUSTOMER_CODE,
        "warehouse_code": INVENTORY_WAREHOUSE_CODE,
        "order_date": date,
        "items": items,
        "notes": "Gift 系统自动同步",
    }

    sync_result = None
    sync_error = None

    try:
        data = _json.dumps(payload).encode("utf-8")
        req = _Request(
            INVENTORY_SYNC_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {INVENTORY_TOKEN}",
            },
        )
        resp = _urlopen(req, timeout=20)
        status = resp.getcode()
        body = resp.read().decode("utf-8", errors="replace")

        if status == 200:
            try:
                resp_json = _json.loads(body)
                if resp_json.get("code") == 0:
                    order_data = resp_json.get("data", {})
                    sync_result = (
                        f"✅ 同步成功\n"
                        f"订单号: {order_data.get('order_number', '-')}\n"
                        f"客户: {order_data.get('customer_name', '-')}\n"
                        f"金额: {order_data.get('total_amount', '-')}\n"
                        f"状态: {order_data.get('status', '-')}"
                    )
                    # Record successful sync
                    db.session.add(InventorySync(sync_date=sync_date))
                    db.session.commit()
                else:
                    sync_error = f"API 返回错误: {resp_json.get('message', body)}"
            except _json.JSONDecodeError:
                sync_result = f"HTTP 200 — {body[:500]}"
        elif status == 404:
            sync_error = f"同步失败 (404): SKU 不存在，请检查商品 SKU 是否与库存系统一致"
        elif status == 400:
            sync_error = f"同步失败 (400): 库存不足 — {body[:300]}"
        elif status == 422:
            sync_error = f"同步失败 (422): 参数校验失败 — {body[:300]}"
        else:
            sync_error = f"同步失败 (HTTP {status}): {body[:300]}"
    except Exception as e:
        # urllib raises HTTPError for 4xx/5xx — extract body
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        code = getattr(e, "code", 0)
        if code == 400:
            sync_error = f"同步失败 (400): {body or str(e)}"
        elif code == 404:
            sync_error = f"同步失败 (404): SKU 不存在 — {body or str(e)}"
        elif code == 422:
            sync_error = f"同步失败 (422): 参数校验失败 — {body or str(e)}"
        else:
            sync_error = f"同步请求失败: {e}{' — ' + body if body else ''}"

    return _sales_render(date, date, "", sync_result=sync_result, sync_error=sync_error, sync_payload=payload)


def _sales_render(date_from, date_to, sku_q, sync_result=None, sync_error=None, sync_payload=None):
    """Helper: re-render sales page with sync feedback."""
    unviewed = Order.query.filter_by(is_viewed=False).count()
    return render_template(
        "admin_sales.html",
        rows=[],
        sku_totals=[],
        sync_dates=[],
        synced_dates={},
        date_from=date_from,
        date_to=date_to,
        sku_q=sku_q,
        inventory_configured=bool(INVENTORY_TOKEN),
        unviewed_count=unviewed,
        session_user=get_admin_user(),
        sync_result=sync_result,
        sync_error=sync_error,
        sync_payload=sync_payload,
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
