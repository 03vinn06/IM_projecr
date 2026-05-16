"""
Online Food Ordering System — Flask Backend
============================================
Single-file backend: routing, session management, business logic.
Database: SQLite (swap DATABASE_URL for PostgreSQL in production).

NEW FEATURES (v2):
  - Rating & Review system (per order / per item)
  - Payment system (cash, GCash, Maya, card) for pickup & delivery
  - Sales reports: daily, weekly, monthly, custom range
  - Most ordered food analytics
  - Admin analytics dashboard
"""

import os
import sqlite3
import functools
from datetime import datetime, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash

# ─────────────────────────────────────────────────────────────
#  APP CONFIGURATION
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod-!!!")

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATABASE     = os.path.join(BASE_DIR, "food_ordering.db")
SCHEMA_FILE  = os.path.join(BASE_DIR, "schema.sql")
DELIVERY_FEE = 3.99
TAX_RATE     = 0.08   # 8 %


# ─────────────────────────────────────────────────────────────
#  DATABASE HELPERS
# ─────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False):
    cur = get_db().execute(sql, params)
    rv  = cur.fetchall()
    return (rv[0] if rv else None) if one else rv


def execute(sql, params=()):
    db  = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur

def rows_to_dicts(rows):
    """Convert sqlite3.Row objects to plain dicts for JSON serialization."""
    return [dict(row) for row in rows]

def init_db():
    """Create tables and seed data if not already present."""
    with app.app_context():
        db = get_db()
        with open(SCHEMA_FILE, "r") as f:
            db.executescript(f.read())
        db.commit()
        admin = query(
            "SELECT id, password_hash FROM users WHERE email = ?",
            ("admin@foodapp.com",), one=True
        )
        if admin and admin["password_hash"].startswith("scrypt:32768:8:1$placeholder"):
            execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash("admin123"), admin["id"])
            )


# ─────────────────────────────────────────────────────────────
#  AUTH DECORATORS
# ─────────────────────────────────────────────────────────────
def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("index"))
        return view(**kwargs)
    return login_required(wrapped)


# ─────────────────────────────────────────────────────────────
#  CONTEXT PROCESSOR
# ─────────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    cart      = session.get("cart", {})
    cart_count = sum(v["qty"] for v in cart.values())
    return dict(
        cart_count=cart_count,
        current_user_name=session.get("user_name"),
        current_role=session.get("role"),
        logged_in="user_id" in session,
    )


# ─────────────────────────────────────────────────────────────
#  PUBLIC ROUTES
# ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    featured = query(
        """SELECT m.*, c.name AS category_name,
                  COALESCE(AVG(r.rating),0) AS avg_rating,
                  COUNT(r.id) AS review_count
           FROM menu_items m
           JOIN categories c ON c.id = m.category_id
           LEFT JOIN reviews r ON r.menu_item_id = m.id
           WHERE m.is_available = 1
           GROUP BY m.id
           ORDER BY RANDOM() LIMIT 6"""
    )
    return render_template("index.html", featured=featured)


@app.route("/menu")
def menu():
    categories = query("SELECT * FROM categories ORDER BY sort_order")
    items_by_cat = {}
    for cat in categories:
        items_by_cat[cat["id"]] = query(
            """SELECT m.*, c.name AS category_name,
                      COALESCE(AVG(r.rating),0) AS avg_rating,
                      COUNT(r.id) AS review_count
               FROM menu_items m
               JOIN categories c ON c.id = m.category_id
               LEFT JOIN reviews r ON r.menu_item_id = m.id
               WHERE m.category_id = ?
               GROUP BY m.id ORDER BY m.is_available DESC, m.name""",
            (cat["id"],)
        )
    return render_template("menu.html", categories=categories, items_by_cat=items_by_cat)


# ─────────────────────────────────────────────────────────────
#  CART (session-based)
# ─────────────────────────────────────────────────────────────
@app.route("/cart/add", methods=["POST"])
def cart_add():
    item_id = str(request.form.get("item_id"))
    qty     = int(request.form.get("qty", 1))
    item    = query("SELECT * FROM menu_items WHERE id = ? AND is_available = 1",
                    (item_id,), one=True)
    if not item:
        flash("Item not available.", "danger")
        return redirect(url_for("menu"))
    cart = session.get("cart", {})
    if item_id in cart:
        cart[item_id]["qty"] += qty
    else:
        cart[item_id] = {"name": item["name"], "price": item["price"], "qty": qty}
    session["cart"] = cart
    flash(f'"{item["name"]}" added to cart!', "success")
    return redirect(request.referrer or url_for("menu"))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    item_id = str(request.form.get("item_id"))
    qty     = int(request.form.get("qty", 1))
    cart    = session.get("cart", {})
    if item_id in cart:
        if qty <= 0:
            cart.pop(item_id)
        else:
            cart[item_id]["qty"] = qty
    session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/cart/remove", methods=["POST"])
def cart_remove():
    item_id = str(request.form.get("item_id"))
    cart    = session.get("cart", {})
    cart.pop(item_id, None)
    session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    cart     = session.get("cart", {})
    subtotal = sum(v["price"] * v["qty"] for v in cart.values())
    return render_template("cart.html", cart=cart, subtotal=subtotal,
                           delivery_fee=DELIVERY_FEE, tax_rate=TAX_RATE)


# ─────────────────────────────────────────────────────────────
#  CHECKOUT  (with payment selection)
# ─────────────────────────────────────────────────────────────
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart = session.get("cart", {})
    if not cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("menu"))

    subtotal        = sum(v["price"] * v["qty"] for v in cart.values())
    payment_methods = query("SELECT * FROM payment_methods ORDER BY id")

    if request.method == "POST":
        fulfillment    = request.form.get("fulfillment")
        instructions   = request.form.get("instructions", "")
        payment_method = request.form.get("payment_method", "cash")
        payment_ref    = request.form.get("payment_reference", "").strip()

        f_row = query("SELECT id FROM fulfillment_types WHERE name = ?", (fulfillment,), one=True)
        if not f_row:
            flash("Invalid fulfillment type.", "danger")
            return redirect(url_for("checkout"))

        delivery_fee = DELIVERY_FEE if fulfillment == "delivery" else 0.0
        tax          = round((subtotal + delivery_fee) * TAX_RATE, 2)
        total        = round(subtotal + delivery_fee + tax, 2)

        delivery_address = delivery_city = delivery_zip = None
        if fulfillment == "delivery":
            delivery_address = request.form.get("address", "").strip()
            delivery_city    = request.form.get("city", "").strip()
            delivery_zip     = request.form.get("zip", "").strip()
            if not all([delivery_address, delivery_city, delivery_zip]):
                flash("Please fill in all delivery address fields.", "warning")
                return redirect(url_for("checkout"))

        status_id = query("SELECT id FROM order_statuses WHERE name = 'pending'", one=True)["id"]

        cur = execute(
            """INSERT INTO orders
               (customer_id, status_id, fulfillment_type_id,
                delivery_address, delivery_city, delivery_zip,
                subtotal, delivery_fee, tax, total, special_instructions)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (session["user_id"], status_id, f_row["id"],
             delivery_address, delivery_city, delivery_zip,
             round(subtotal, 2), delivery_fee, tax, total, instructions)
        )
        order_id = cur.lastrowid

        for item_id, v in cart.items():
            execute(
                """INSERT INTO order_items (order_id, menu_item_id, quantity, unit_price)
                   VALUES (?,?,?,?)""",
                (order_id, int(item_id), v["qty"], v["price"])
            )

        execute(
            """INSERT INTO order_status_log (order_id, status_id, changed_by, note)
               VALUES (?,?,?,?)""",
            (order_id, status_id, session["user_id"], "Order placed by customer")
        )

        # Payment record
        pm_row = query("SELECT id FROM payment_methods WHERE name = ?", (payment_method,), one=True)
        if pm_row:
            ps_row = query("SELECT id FROM payment_statuses WHERE name = 'pending'", one=True)
            execute(
                """INSERT INTO payments (order_id, payment_method_id, payment_status_id, amount, reference_number)
                   VALUES (?,?,?,?,?)""",
                (order_id, pm_row["id"], ps_row["id"], total,
                 payment_ref if payment_ref else None)
            )

        session.pop("cart", None)
        flash(f"🎉 Order #{order_id} placed successfully!", "success")
        return redirect(url_for("order_confirmation", order_id=order_id))

    return render_template("checkout.html", cart=cart, subtotal=subtotal,
                           delivery_fee=DELIVERY_FEE, tax_rate=TAX_RATE,
                           payment_methods=payment_methods)


@app.route("/orders/<int:order_id>")
@login_required
def order_confirmation(order_id):
    order = query(
        """SELECT o.*, os.name AS status_name, ft.name AS fulfillment_name,
                  u.full_name AS customer_name
           FROM orders o
           JOIN order_statuses os ON os.id = o.status_id
           JOIN fulfillment_types ft ON ft.id = o.fulfillment_type_id
           JOIN users u ON u.id = o.customer_id
           WHERE o.id = ?""",
        (order_id,), one=True
    )
    if not order or (order["customer_id"] != session["user_id"]
                     and session.get("role") != "admin"):
        flash("Order not found.", "danger")
        return redirect(url_for("index"))

    items = query(
        """SELECT oi.*, m.name AS item_name, m.image_url
           FROM order_items oi JOIN menu_items m ON m.id = oi.menu_item_id
           WHERE oi.order_id = ?""",
        (order_id,)
    )
    payment = query(
        """SELECT p.*, pm.name AS method_name, ps.name AS status_name
           FROM payments p
           JOIN payment_methods pm ON pm.id = p.payment_method_id
           JOIN payment_statuses ps ON ps.id = p.payment_status_id
           WHERE p.order_id = ?""",
        (order_id,), one=True
    )
    existing_review = query(
        "SELECT id FROM reviews WHERE order_id = ? AND customer_id = ? AND menu_item_id IS NULL",
        (order_id, session["user_id"]), one=True
    )
    return render_template("order_confirmation.html", order=order, items=items,
                           payment=payment, existing_review=existing_review)


@app.route("/my-orders")
@login_required
def my_orders():
    orders = query(
        """SELECT o.*, os.name AS status_name, ft.name AS fulfillment_name,
                  pm.name AS payment_method, ps.name AS payment_status
           FROM orders o
           JOIN order_statuses os    ON os.id = o.status_id
           JOIN fulfillment_types ft ON ft.id = o.fulfillment_type_id
           LEFT JOIN payments p      ON p.order_id = o.id
           LEFT JOIN payment_methods pm ON pm.id = p.payment_method_id
           LEFT JOIN payment_statuses ps ON ps.id = p.payment_status_id
           WHERE o.customer_id = ?
           ORDER BY o.created_at DESC""",
        (session["user_id"],)
    )
    return render_template("my_orders.html", orders=orders)


# ─────────────────────────────────────────────────────────────
#  REVIEWS
# ─────────────────────────────────────────────────────────────
@app.route("/orders/<int:order_id>/review", methods=["GET", "POST"])
@login_required
def leave_review(order_id):
    order = query(
        """SELECT o.*, os.name AS status_name
           FROM orders o JOIN order_statuses os ON os.id = o.status_id
           WHERE o.id = ? AND o.customer_id = ?""",
        (order_id, session["user_id"]), one=True
    )
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("my_orders"))

    if order["status_name"] not in ("delivered", "ready", "picked_up"):
        flash("You can only review completed orders.", "warning")
        return redirect(url_for("my_orders"))

    items = query(
        """SELECT oi.*, m.name AS item_name, m.image_url
           FROM order_items oi JOIN menu_items m ON m.id = oi.menu_item_id
           WHERE oi.order_id = ?""",
        (order_id,)
    )

    if request.method == "POST":
        overall_rating  = request.form.get("overall_rating")
        overall_comment = request.form.get("overall_comment", "").strip()

        if overall_rating:
            try:
                execute(
                    """INSERT OR REPLACE INTO reviews
                       (order_id, customer_id, menu_item_id, rating, comment)
                       VALUES (?,?,NULL,?,?)""",
                    (order_id, session["user_id"], int(overall_rating), overall_comment)
                )
            except Exception:
                pass

        for item in items:
            item_rating  = request.form.get(f"item_rating_{item['menu_item_id']}")
            item_comment = request.form.get(f"item_comment_{item['menu_item_id']}", "").strip()
            if item_rating:
                try:
                    execute(
                        """INSERT OR REPLACE INTO reviews
                           (order_id, customer_id, menu_item_id, rating, comment)
                           VALUES (?,?,?,?,?)""",
                        (order_id, session["user_id"],
                         item["menu_item_id"], int(item_rating), item_comment)
                    )
                except Exception:
                    pass

        flash("Thank you for your review! 🌟", "success")
        return redirect(url_for("my_orders"))

    existing = {r["menu_item_id"]: r for r in query(
        "SELECT * FROM reviews WHERE order_id = ? AND customer_id = ?",
        (order_id, session["user_id"])
    )}
    return render_template("leave_review.html", order=order, items=items, existing=existing)


@app.route("/menu/<int:item_id>/reviews")
def item_reviews(item_id):
    item = query(
        """SELECT m.*, c.name AS category_name
           FROM menu_items m JOIN categories c ON c.id = m.category_id
           WHERE m.id = ?""",
        (item_id,), one=True
    )
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for("menu"))
    reviews = query(
        """SELECT r.*, u.full_name AS reviewer_name
           FROM reviews r JOIN users u ON u.id = r.customer_id
           WHERE r.menu_item_id = ?
           ORDER BY r.created_at DESC""",
        (item_id,)
    )
    stats = query(
        """SELECT COALESCE(AVG(rating),0) AS avg_rating, COUNT(*) AS total
           FROM reviews WHERE menu_item_id = ?""",
        (item_id,), one=True
    )
    return render_template("item_reviews.html", item=item, reviews=reviews, stats=stats)


# ─────────────────────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        name     = request.form.get("full_name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone    = request.form.get("phone", "").strip()
        if not all([name, email, password]):
            flash("Please fill in all required fields.", "warning")
            return redirect(url_for("register"))
        if query("SELECT id FROM users WHERE email = ?", (email,), one=True):
            flash("Email already registered. Please log in.", "warning")
            return redirect(url_for("login"))
        role_id = query("SELECT id FROM roles WHERE name = 'customer'", one=True)["id"]
        execute(
            "INSERT INTO users (role_id, full_name, email, password_hash, phone) VALUES (?,?,?,?,?)",
            (role_id, name, email, generate_password_hash(password), phone)
        )
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user     = query(
            """SELECT u.*, r.name AS role_name
               FROM users u JOIN roles r ON r.id = u.role_id
               WHERE u.email = ?""",
            (email,), one=True
        )
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"]   = user["id"]
            session["user_name"] = user["full_name"]
            session["role"]      = user["role_name"]
            flash(f'Welcome back, {user["full_name"]}!', "success")
            if user["role_name"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("index"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ─────────────────────────────────────────────────────────────
#  ADMIN ROUTES
# ─────────────────────────────────────────────────────────────
@app.route("/admin")
@admin_required
def admin_dashboard():
    total_orders   = query("SELECT COUNT(*) AS n FROM orders", one=True)["n"]
    pending_orders = query(
        "SELECT COUNT(*) AS n FROM orders WHERE status_id = (SELECT id FROM order_statuses WHERE name='pending')",
        one=True
    )["n"]
    total_revenue  = query(
        "SELECT COALESCE(SUM(total),0) AS s FROM orders WHERE status_id != (SELECT id FROM order_statuses WHERE name='cancelled')",
        one=True
    )["s"]
    total_items    = query("SELECT COUNT(*) AS n FROM menu_items", one=True)["n"]
    recent_orders  = query(
        """SELECT o.*, os.name AS status_name, ft.name AS fulfillment_name, u.full_name AS customer_name,
                  pm.name AS payment_method, ps.name AS payment_status
           FROM orders o
           JOIN order_statuses os    ON os.id = o.status_id
           JOIN fulfillment_types ft ON ft.id = o.fulfillment_type_id
           JOIN users u ON u.id = o.customer_id
           LEFT JOIN payments p ON p.order_id = o.id
           LEFT JOIN payment_methods pm ON pm.id = p.payment_method_id
           LEFT JOIN payment_statuses ps ON ps.id = p.payment_status_id
           ORDER BY o.created_at DESC LIMIT 10"""
    )
    today_revenue = query(
        """SELECT COALESCE(SUM(total),0) AS s FROM orders
           WHERE DATE(created_at) = DATE('now')
           AND status_id != (SELECT id FROM order_statuses WHERE name='cancelled')""",
        one=True
    )["s"]
    top_item = query(
        """SELECT m.name, SUM(oi.quantity) AS total_qty
           FROM order_items oi
           JOIN menu_items m ON m.id = oi.menu_item_id
           JOIN orders o ON o.id = oi.order_id
           WHERE DATE(o.created_at) = DATE('now')
           GROUP BY oi.menu_item_id ORDER BY total_qty DESC LIMIT 1""",
        one=True
    )
    avg_rating = query(
        "SELECT COALESCE(AVG(rating),0) AS avg FROM reviews WHERE menu_item_id IS NULL",
        one=True
    )["avg"]
    return render_template("admin/dashboard.html",
                           total_orders=total_orders,
                           pending_orders=pending_orders,
                           total_revenue=total_revenue,
                           total_items=total_items,
                           recent_orders=recent_orders,
                           today_revenue=today_revenue,
                           top_item=top_item,
                           avg_rating=avg_rating)


@app.route("/admin/orders")
@admin_required
def admin_orders():
    status_filter = request.args.get("status", "all")
    statuses      = query("SELECT * FROM order_statuses ORDER BY id")

    base_sql = """SELECT o.*, os.name AS status_name, ft.name AS fulfillment_name, u.full_name AS customer_name,
                         pm.name AS payment_method, ps.name AS payment_status
               FROM orders o
               JOIN order_statuses os    ON os.id = o.status_id
               JOIN fulfillment_types ft ON ft.id = o.fulfillment_type_id
               JOIN users u ON u.id = o.customer_id
               LEFT JOIN payments p ON p.order_id = o.id
               LEFT JOIN payment_methods pm ON pm.id = p.payment_method_id
               LEFT JOIN payment_statuses ps ON ps.id = p.payment_status_id"""

    if status_filter == "all":
        orders = query(base_sql + " ORDER BY o.created_at DESC")
    else:
        orders = query(base_sql + " WHERE os.name = ? ORDER BY o.created_at DESC", (status_filter,))

    return render_template("admin/orders.html", orders=orders,
                           statuses=statuses, current_filter=status_filter)


@app.route("/admin/orders/<int:order_id>")
@admin_required
def admin_order_detail(order_id):
    order = query(
        """SELECT o.*, os.name AS status_name, ft.name AS fulfillment_name,
                  u.full_name AS customer_name, u.email, u.phone
           FROM orders o
           JOIN order_statuses os    ON os.id = o.status_id
           JOIN fulfillment_types ft ON ft.id = o.fulfillment_type_id
           JOIN users u ON u.id = o.customer_id
           WHERE o.id = ?""",
        (order_id,), one=True
    )
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("admin_orders"))

    items    = query(
        """SELECT oi.*, m.name AS item_name, m.image_url
           FROM order_items oi JOIN menu_items m ON m.id = oi.menu_item_id
           WHERE oi.order_id = ?""",
        (order_id,)
    )
    statuses = query("SELECT * FROM order_statuses ORDER BY id")
    logs     = query(
        """SELECT sl.*, os.name AS status_name, u.full_name AS changed_by_name
           FROM order_status_log sl
           JOIN order_statuses os ON os.id = sl.status_id
           LEFT JOIN users u ON u.id = sl.changed_by
           WHERE sl.order_id = ?
           ORDER BY sl.changed_at""",
        (order_id,)
    )
    payment = query(
        """SELECT p.*, pm.name AS method_name, ps.name AS status_name
           FROM payments p
           JOIN payment_methods pm ON pm.id = p.payment_method_id
           JOIN payment_statuses ps ON ps.id = p.payment_status_id
           WHERE p.order_id = ?""",
        (order_id,), one=True
    )
    payment_statuses_list = query("SELECT * FROM payment_statuses ORDER BY id")
    review = query(
        """SELECT r.*, u.full_name AS reviewer_name
           FROM reviews r JOIN users u ON u.id = r.customer_id
           WHERE r.order_id = ? AND r.menu_item_id IS NULL""",
        (order_id,), one=True
    )
    return render_template("admin/order_detail.html",
                           order=order, items=items, statuses=statuses, logs=logs,
                           payment=payment, payment_statuses=payment_statuses_list,
                           review=review)


@app.route("/admin/orders/<int:order_id>/update-status", methods=["POST"])
@admin_required
def admin_update_status(order_id):
    new_status_name = request.form.get("status")
    note            = request.form.get("note", "")
    status = query("SELECT id FROM order_statuses WHERE name = ?", (new_status_name,), one=True)
    if not status:
        flash("Invalid status.", "danger")
        return redirect(url_for("admin_order_detail", order_id=order_id))
    execute("UPDATE orders SET status_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status["id"], order_id))
    execute(
        "INSERT INTO order_status_log (order_id, status_id, changed_by, note) VALUES (?,?,?,?)",
        (order_id, status["id"], session["user_id"], note)
    )
    flash(f"Order #{order_id} status updated to '{new_status_name}'.", "success")
    return redirect(url_for("admin_order_detail", order_id=order_id))


@app.route("/admin/orders/<int:order_id>/update-payment", methods=["POST"])
@admin_required
def admin_update_payment(order_id):
    new_status = request.form.get("payment_status")
    ps_row = query("SELECT id FROM payment_statuses WHERE name = ?", (new_status,), one=True)
    if ps_row:
        if new_status == "paid":
            execute("UPDATE payments SET payment_status_id = ?, paid_at = CURRENT_TIMESTAMP WHERE order_id = ?",
                    (ps_row["id"], order_id))
        else:
            execute("UPDATE payments SET payment_status_id = ? WHERE order_id = ?",
                    (ps_row["id"], order_id))
        flash(f"Payment status updated to '{new_status}'.", "success")
    return redirect(url_for("admin_order_detail", order_id=order_id))


@app.route("/admin/menu")
@admin_required
def admin_menu():
    items = query(
        """SELECT m.*, c.name AS category_name,
                  COALESCE(AVG(r.rating),0) AS avg_rating,
                  COUNT(r.id) AS review_count
           FROM menu_items m
           JOIN categories c ON c.id = m.category_id
           LEFT JOIN reviews r ON r.menu_item_id = m.id
           GROUP BY m.id
           ORDER BY c.sort_order, m.name"""
    )
    categories = query("SELECT * FROM categories ORDER BY sort_order")
    return render_template("admin/menu.html", items=items, categories=categories)


@app.route("/admin/menu/add", methods=["POST"])
@admin_required
def admin_menu_add():
    name        = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    price       = float(request.form.get("price", 0))
    category_id = int(request.form.get("category_id", 1))
    image_url   = request.form.get("image_url", "").strip()
    if not name or price <= 0:
        flash("Name and a valid price are required.", "warning")
        return redirect(url_for("admin_menu"))
    execute(
        "INSERT INTO menu_items (category_id, name, description, price, image_url) VALUES (?,?,?,?,?)",
        (category_id, name, description, price, image_url or None)
    )
    flash(f'Menu item "{name}" added.', "success")
    return redirect(url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/edit", methods=["POST"])
@admin_required
def admin_menu_edit(item_id):
    execute(
        """UPDATE menu_items SET name=?, description=?, price=?,
           category_id=?, image_url=?, is_available=?,
           updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (request.form.get("name"), request.form.get("description"),
         float(request.form.get("price", 0)), int(request.form.get("category_id", 1)),
         request.form.get("image_url") or None,
         1 if request.form.get("is_available") else 0, item_id)
    )
    flash("Menu item updated.", "success")
    return redirect(url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/delete", methods=["POST"])
@admin_required
def admin_menu_delete(item_id):
    execute("UPDATE menu_items SET is_available = 0 WHERE id = ?", (item_id,))
    flash("Menu item hidden from customers.", "info")
    return redirect(url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/toggle", methods=["POST"])
@admin_required
def admin_menu_toggle(item_id):
    """Quick-toggle availability for a menu item."""
    item = query("SELECT id, name, is_available FROM menu_items WHERE id = ?", (item_id,), one=True)
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for("admin_menu"))
    new_status = 0 if item["is_available"] else 1
    execute(
        "UPDATE menu_items SET is_available = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, item_id)
    )
    status_label = "available" if new_status else "unavailable"
    flash(f'"{item["name"]}" marked as {status_label}.', "success")
    return redirect(url_for("admin_menu"))


# ─────────────────────────────────────────────────────────────
#  ADMIN — REVIEWS MANAGEMENT
# ─────────────────────────────────────────────────────────────
@app.route("/admin/reviews")
@admin_required
def admin_reviews():
    reviews = query(
        """SELECT r.*, u.full_name AS reviewer_name,
                  m.name AS item_name, o.id AS order_id
           FROM reviews r
           JOIN users u ON u.id = r.customer_id
           JOIN orders o ON o.id = r.order_id
           LEFT JOIN menu_items m ON m.id = r.menu_item_id
           ORDER BY r.created_at DESC"""
    )
    stats = query(
        """SELECT
             COALESCE(AVG(CASE WHEN menu_item_id IS NULL THEN rating END), 0) AS avg_overall,
             COUNT(CASE WHEN menu_item_id IS NULL THEN 1 END) AS total_overall,
             COALESCE(AVG(CASE WHEN menu_item_id IS NOT NULL THEN rating END), 0) AS avg_item,
             COUNT(CASE WHEN menu_item_id IS NOT NULL THEN 1 END) AS total_item
           FROM reviews""",
        one=True
    )
    return render_template("admin/reviews.html", reviews=reviews, stats=stats)


@app.route("/admin/reviews/<int:review_id>/delete", methods=["POST"])
@admin_required
def admin_delete_review(review_id):
    execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    flash("Review deleted.", "info")
    return redirect(url_for("admin_reviews"))


# ─────────────────────────────────────────────────────────────
#  ADMIN — ANALYTICS & REPORTS
# ─────────────────────────────────────────────────────────────
@app.route("/admin/analytics")
@admin_required
def admin_analytics():
    period    = request.args.get("period", "week")
    date_from = request.args.get("from", "")
    date_to   = request.args.get("to", "")
    today     = datetime.now()

    if period == "today":
        start = today.strftime("%Y-%m-%d")
        end   = today.strftime("%Y-%m-%d")
        label = "Today"
    elif period == "week":
        start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
        end   = today.strftime("%Y-%m-%d")
        label = "Last 7 Days"
    elif period == "month":
        start = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        end   = today.strftime("%Y-%m-%d")
        label = "Last 30 Days"
    elif period == "custom" and date_from and date_to:
        start = date_from
        end   = date_to
        label = f"{date_from} to {date_to}"
    else:
        start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
        end   = today.strftime("%Y-%m-%d")
        label = "Last 7 Days"
        period = "week"

    cancelled_id = query("SELECT id FROM order_statuses WHERE name='cancelled'", one=True)["id"]

    summary = query(
        """SELECT COUNT(*) AS total_orders,
                  COALESCE(SUM(total), 0) AS total_revenue,
                  COALESCE(AVG(total), 0) AS avg_order_value,
                  COUNT(CASE WHEN ft.name = 'delivery' THEN 1 END) AS delivery_count,
                  COUNT(CASE WHEN ft.name = 'pickup'   THEN 1 END) AS pickup_count
           FROM orders o
           JOIN fulfillment_types ft ON ft.id = o.fulfillment_type_id
           WHERE DATE(o.created_at) BETWEEN ? AND ?
           AND o.status_id != ?""",
        (start, end, cancelled_id), one=True
    )

    daily_revenue = query(
        """SELECT DATE(created_at) AS day, COUNT(*) AS orders,
                  COALESCE(SUM(total), 0) AS revenue
           FROM orders
           WHERE DATE(created_at) BETWEEN ? AND ? AND status_id != ?
           GROUP BY day ORDER BY day""",
        (start, end, cancelled_id)
    )

    top_items = query(
        """SELECT m.name, m.image_url,
                  SUM(oi.quantity) AS total_qty,
                  SUM(oi.quantity * oi.unit_price) AS total_revenue,
                  COALESCE(AVG(r.rating), 0) AS avg_rating,
                  COUNT(DISTINCT r.id) AS review_count
           FROM order_items oi
           JOIN menu_items m ON m.id = oi.menu_item_id
           JOIN orders o ON o.id = oi.order_id
           LEFT JOIN reviews r ON r.menu_item_id = m.id
           WHERE DATE(o.created_at) BETWEEN ? AND ? AND o.status_id != ?
           GROUP BY oi.menu_item_id
           ORDER BY total_qty DESC LIMIT 10""",
        (start, end, cancelled_id)
    )

    by_category = query(
        """SELECT c.name AS category,
                  SUM(oi.quantity) AS total_qty,
                  COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS revenue
           FROM order_items oi
           JOIN menu_items m ON m.id = oi.menu_item_id
           JOIN categories c ON c.id = m.category_id
           JOIN orders o ON o.id = oi.order_id
           WHERE DATE(o.created_at) BETWEEN ? AND ? AND o.status_id != ?
           GROUP BY c.id ORDER BY revenue DESC""",
        (start, end, cancelled_id)
    )

    by_payment = query(
        """SELECT pm.name AS method, COUNT(p.id) AS count,
                  COALESCE(SUM(p.amount), 0) AS total
           FROM payments p
           JOIN payment_methods pm ON pm.id = p.payment_method_id
           JOIN orders o ON o.id = p.order_id
           WHERE DATE(o.created_at) BETWEEN ? AND ?
           GROUP BY pm.id ORDER BY total DESC""",
        (start, end)
    )

    hourly = query(
        """SELECT CAST(strftime('%H', created_at) AS INTEGER) AS hour, COUNT(*) AS orders
           FROM orders
           WHERE DATE(created_at) BETWEEN ? AND ?
           GROUP BY hour ORDER BY hour""",
        (start, end)
    )

    return render_template("admin/analytics.html",
                       period=period, label=label,
                       date_from=start, date_to=end,
                       summary=dict(summary) if summary else {},
                       daily_revenue=rows_to_dicts(daily_revenue),
                       top_items=rows_to_dicts(top_items),
                       by_category=rows_to_dicts(by_category),
                       by_payment=rows_to_dicts(by_payment),
                       hourly=rows_to_dicts(hourly))


# ─────────────────────────────────────────────────────────────
#  API (JSON)
# ─────────────────────────────────────────────────────────────
@app.route("/api/cart-summary")
def api_cart_summary():
    cart     = session.get("cart", {})
    subtotal = sum(v["price"] * v["qty"] for v in cart.values())
    delivery = DELIVERY_FEE
    tax      = round((subtotal + delivery) * TAX_RATE, 2)
    return jsonify({
        "subtotal":     round(subtotal, 2),
        "delivery_fee": delivery,
        "tax":          tax,
        "total":        round(subtotal + delivery + tax, 2),
        "item_count":   sum(v["qty"] for v in cart.values()),
    })


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
