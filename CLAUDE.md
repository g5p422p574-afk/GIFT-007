# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gift is a single-store/warehouse order management system. Store owners register accounts, browse a shared product catalog, place orders (with payment proof uploads), and track shipments. An admin panel manages products, confirms/ships orders, processes after-sales, and views financial reports.

## Tech Stack

- **Python 3** / Flask 3.x / Flask-SQLAlchemy
- **Database**: SQLite (dev) / MySQL via PyMySQL (production on Alibaba Cloud RDS)
- **Templates**: Server-rendered Jinja2 (no JS framework, vanilla JS for interactivity)
- **Auth**: Werkzeug password hashing, Flask signed-cookie sessions
- **Production**: Gunicorn + Nginx reverse proxy, systemd service

## Running Locally

```bash
cd GIFT-007
# Dev mode (SQLite):
python app.py
# Production mode (MySQL RDS):
GIFT_ENV=production python app.py
```

The app starts at `http://localhost:5000`. Default admin: `admin` / `REMOVED_ADMIN_PASSWORD`.

## Production Deployment (Alibaba Cloud ECS)

- **Server**: `106.15.61.246` (root / REMOVED_DB_PASSWORD)
- **Project path**: `/var/www/gift/`
- **Service**: `systemctl restart gift` (gunicorn 2 workers, preload, bind 127.0.0.1:8000)
- **Nginx**: reverse proxy on port 80 → gunicorn on 8000
- **RDS MySQL**: `rm-uf6d744cennmvjx1pyo.mysql.rds.aliyuncs.com` / `srdz_888`
- **Deploy flow**: Upload changed files via SFTP to `/var/www/gift/`, then `systemctl restart gift`
- **DB backup**: No mysqldump on server; migration is additive-only (ALTER TABLE ADD COLUMN, INSERT), never destructive

## Key Architecture (multi-store — 2026-06-03)

A **User** (login by phone) can own multiple **Store** records. Each Store has its own **Addresses** and **Orders**. Session tracks `user_id` + `store_id`. On upgrade from old schema (User=Store), an auto-migration in `app.py` adds `store_id` columns and creates Store records.

### Models (`models.py`)

| Model | Key FK | Notes |
|-------|--------|-------|
| `User` | — | phone, password_hash, is_admin, store_name (legacy default for first store) |
| `Store` | user_id → User | store_name, one user has many stores |
| `Product` | — | Global catalog (not per-store), is_out_of_stock flag |
| `Order` | store_id → Store, user_id (legacy) | status: ordered→confirmed→shipped; after-sale fields |
| `OrderItem` | order_id → Order, product_id → Product | quantity, unit_price |
| `Address` | store_id → Store, user_id (legacy) | is_default flag per store |

`order.user_id` and `address.user_id` are legacy columns kept for migration safety; all new code uses `store_id`.

### Blueprints

| Blueprint | Prefix | File | Auth |
|-----------|--------|------|------|
| `home_bp` | `/` | `routes/home.py` | Public + login_required + store_manage |
| `orders_bp` | `/orders` | `routes/orders.py` | Client (store_id) + Admin |
| `products_bp` | `/admin` | `routes/products.py` | admin_required |

### Session keys

- Client login: `session["user_id"]`, `session["store_id"]`
- Admin login: `session["admin_id"]`, `session["is_admin"] = True`
- Cart: `session["cart"]` = `{product_id_str: quantity}` (not persisted to DB)

### Store migration (`app.py`)

On startup, checks if `store_id` column exists on `order`/`address` tables. If not, ALTER TABLE to add it. Then creates a `Store` for each non-admin `User` that has none, and backfills `store_id` on existing `Address`/`Order`. Idempotent — safe to restart.

### Template nav (base.html)

Two completely different nav bars: admin vs client. Client nav shows current store name, "切换门店" button, "设置", "退出".
