# 🍽️ Saffron & Salt — Online Food Ordering System

A full-stack Flask web application for online food ordering with customer and admin portals.

---

## 📁 Project Structure

```
food_ordering/
├── app.py                        # Single-file Flask backend
├── schema.sql                    # Standalone DB schema (SQLite)
├── requirements.txt
└── templates/
    ├── base.html                 # Shared layout & navbar
    ├── index.html                # Homepage (hero, featured dishes)
    ├── menu.html                 # Full browsable menu
    ├── cart.html                 # Shopping cart
    ├── checkout.html             # Pickup/delivery checkout
    ├── order_confirmation.html   # Post-order success page
    ├── my_orders.html            # Customer order history
    ├── login.html                # Auth — sign in
    ├── register.html             # Auth — sign up
    └── admin/
        ├── base_admin.html       # Admin shell with sidebar
        ├── dashboard.html        # KPI stats + recent orders
        ├── orders.html           # Filterable orders list
        ├── order_detail.html     # Manage individual order
        └── menu.html             # CRUD menu items
```

---

## 🚀 Quick Start

```bash
# 1. Create & activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app (DB is auto-created on first launch)
python app.py
```

Open **http://localhost:5000** in your browser.

**Demo credentials**
| Role     | Email               | Password  |
|----------|---------------------|-----------|
| Admin    | admin@foodapp.com   | admin123  |
| Customer | register a new account via /register | — |

> ⚠️ Change `SECRET_KEY` and the admin password before any public deployment.

---

## ✅ Implemented Features

### Customer Portal
- **Browse menu** by category with live quantity selector
- **Category filter tabs** (sticky, scrollable on mobile)
- **Session-based cart** — add, update quantity, remove items
- **Live cart summary** via `/api/cart-summary` JSON endpoint
- **Checkout** with fulfillment choice:
  - 🏪 **Pickup** — no extra charge
  - 🛵 **Delivery** — $3.99 fee, address form revealed dynamically
- Special instructions field
- Tax (8%) calculated at checkout
- **Order confirmation** page with full receipt breakdown
- **My Orders** — full order history with status badges
- **Account registration & login** with password-show toggle
- Secure session logout

### Admin Portal
- **Dashboard** — total orders, pending count, revenue, menu item count + recent orders table
- **Orders list** — filterable by status (pending / confirmed / preparing / ready / out for delivery / delivered / cancelled)
- **Order detail** — full customer info, itemized receipt, delivery address, special notes
- **Status management** — update order status with optional admin note; full audit log timeline
- **Menu CRUD**:
  - Add new items (name, price, description, category, image URL)
  - Edit existing items via modal dialog (all fields including availability toggle)
  - Soft-delete (hide) items from customers
- Role-based access control — admin routes protected by `@admin_required`

### Security
- Passwords hashed with Werkzeug `generate_password_hash` (scrypt)
- Session-based authentication with `flask.session`
- CSRF protection via Flask's session secret key (upgrade to Flask-WTF for production)
- Role enforcement via decorator chain: `@admin_required` wraps `@login_required`
- Foreign key constraints enforced at the SQLite level

---

## 🗃️ Database Design & Normalization

### Schema overview (9 tables)

| Table              | Purpose                                          |
|--------------------|--------------------------------------------------|
| `roles`            | Lookup: customer / admin                        |
| `users`            | Unified user table (role FK → avoids duplication)|
| `categories`       | Menu categories with sort order                 |
| `menu_items`       | Dishes (FK to categories)                       |
| `fulfillment_types`| Lookup: pickup / delivery                       |
| `order_statuses`   | Lookup: pending → delivered / cancelled         |
| `orders`           | Order header (FK to user, status, fulfillment)  |
| `order_items`      | Line items (FK to order + menu_item)            |
| `order_status_log` | Audit trail of status changes                   |

### Normalization applied

**1NF — First Normal Form**
- Every table has a single-column surrogate primary key (auto-increment integer).
- All column values are atomic — no comma-separated lists, no repeating groups.
- Example: delivery address is split into `delivery_address`, `delivery_city`, `delivery_zip`.

**2NF — Second Normal Form**
- All non-key attributes depend on the *entire* primary key.
- `order_items` has a composite key `(order_id, menu_item_id)`.
  - `quantity` and `unit_price` depend on *both* columns, not just `order_id` or `menu_item_id` alone.
- `menu_items.price` depends only on its own PK, not on category — correct.

**3NF — Third Normal Form**
- No transitive dependencies (non-key → non-key).
- `category_name` is stored **once** in `categories`; `menu_items` only stores `category_id`.
  - If we stored `category_name` in `menu_items`, a rename would require updating every row — a transitive dependency violation.
- Order status labels live in `order_statuses`; `orders` stores only `status_id`.
- Fulfillment type names live in `fulfillment_types`; `orders` stores only `fulfillment_type_id`.
- User role names live in `roles`; `users` stores only `role_id`.
- `unit_price` in `order_items` is a deliberate *snapshot* (not a FK to `menu_items.price`) — this is correct design, not a normalization violation, because prices change over time and historical orders must reflect the price at placement.

### Entity Relationships

```
roles ←── users ──────────────┐
                               │
categories ←── menu_items ─── order_items ──→ orders ──→ order_statuses
                                                │        ──→ fulfillment_types
                                                │        ──→ users (customer)
                                                └──→ order_status_log
```

---

## 🔧 Configuration

| Variable       | Default                        | Description            |
|----------------|--------------------------------|------------------------|
| `SECRET_KEY`   | `dev-secret-change-in-prod-!!!`| Flask session key      |
| `DATABASE`     | `./food_ordering.db`           | SQLite file path       |
| `DELIVERY_FEE` | `3.99`                         | Flat delivery charge   |
| `TAX_RATE`     | `0.08`                         | Tax percentage (8%)    |

Set `SECRET_KEY` via environment variable for production:
```bash
export SECRET_KEY="a-very-long-random-string"
```

---

## 🛣️ API Endpoint Reference

| Method | Path                                  | Auth     | Description               |
|--------|---------------------------------------|----------|---------------------------|
| GET    | `/`                                   | Public   | Homepage                  |
| GET    | `/menu`                               | Public   | Full menu                 |
| POST   | `/cart/add`                           | Public   | Add item to cart          |
| POST   | `/cart/update`                        | Public   | Change quantity           |
| POST   | `/cart/remove`                        | Public   | Remove item               |
| GET    | `/cart`                               | Public   | View cart                 |
| GET    | `/api/cart-summary`                   | Public   | JSON totals               |
| GET/POST | `/checkout`                        | Customer | Place order               |
| GET    | `/orders/<id>`                        | Customer | Order confirmation        |
| GET    | `/my-orders`                          | Customer | Order history             |
| GET/POST | `/register`                        | Public   | Create account            |
| GET/POST | `/login`                           | Public   | Sign in                   |
| GET    | `/logout`                             | Any      | Sign out                  |
| GET    | `/admin`                              | Admin    | Dashboard                 |
| GET    | `/admin/orders`                       | Admin    | Orders list               |
| GET    | `/admin/orders/<id>`                  | Admin    | Order detail              |
| POST   | `/admin/orders/<id>/update-status`    | Admin    | Change status             |
| GET    | `/admin/menu`                         | Admin    | Menu list                 |
| POST   | `/admin/menu/add`                     | Admin    | Add item                  |
| POST   | `/admin/menu/<id>/edit`               | Admin    | Edit item                 |
| POST   | `/admin/menu/<id>/delete`             | Admin    | Soft-delete item          |
