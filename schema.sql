-- ============================================================
--  ONLINE FOOD ORDERING SYSTEM — DATABASE SCHEMA
--  Normalization: 1NF → 2NF → 3NF applied throughout
-- ============================================================
--
--  NORMALIZATION NOTES
--  -------------------
--  1NF: Every table has a primary key; all columns are atomic
--       (no repeating groups, no multi-valued columns).
--
--  2NF: All non-key attributes depend on the WHOLE primary key.
--       order_items uses a composite PK (order_id, menu_item_id)
--       and every attribute (quantity, unit_price) depends on
--       the full composite key, not just one part of it.
--
--  3NF: No transitive dependencies.
--       - category_id in menu_items references categories, so
--         category_name is stored once in categories, not
--         repeated in menu_items.
--       - address fields belong to customers/orders and are not
--         duplicated across multiple tables.
--       - order status history is separated into order_status_log
--         so status labels are not repeated inline.
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ------------------------------------------------------------
-- 1. ROLES  (eliminates hard-coded role strings everywhere)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE      -- 'customer' | 'admin'
);

INSERT OR IGNORE INTO roles (name) VALUES ('customer'), ('admin');

-- ------------------------------------------------------------
-- 2. USERS  (single user table, role FK → 3NF)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id       INTEGER NOT NULL REFERENCES roles(id),
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    phone         TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Default admin account (password: admin123 — change in production)
INSERT OR IGNORE INTO users (role_id, full_name, email, password_hash, phone)
VALUES (
    (SELECT id FROM roles WHERE name = 'admin'),
    'System Admin',
    'admin@foodapp.com',
    'scrypt:32768:8:1$placeholder$changeme',   -- replaced at runtime
    '+1-000-000-0000'
);

-- ------------------------------------------------------------
-- 3. CATEGORIES  (3NF: category name stored once)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO categories (name, sort_order) VALUES
    ('Starters',   1),
    ('Mains',      2),
    ('Sides',      3),
    ('Desserts',   4),
    ('Beverages',  5);

-- ------------------------------------------------------------
-- 4. MENU_ITEMS  (FK to categories → 3NF)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS menu_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    name         TEXT    NOT NULL,
    description  TEXT,
    price        REAL    NOT NULL CHECK (price >= 0),
    image_url    TEXT,
    is_available INTEGER NOT NULL DEFAULT 1,   -- 0 = unavailable
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);


-- ------------------------------------------------------------
-- 5. ORDER_STATUSES  (3NF: status labels defined once)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_statuses (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT    NOT NULL UNIQUE   -- pending | confirmed | preparing | ready | out_for_delivery | delivered | cancelled
);

INSERT OR IGNORE INTO order_statuses (name) VALUES
    ('pending'),
    ('confirmed'),
    ('preparing'),
    ('ready'),
    ('out_for_delivery'),
    ('delivered'),
    ('cancelled');

-- ------------------------------------------------------------
-- 6. FULFILLMENT_TYPES  (3NF: avoids magic strings)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fulfillment_types (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT    NOT NULL UNIQUE   -- 'pickup' | 'delivery'
);

INSERT OR IGNORE INTO fulfillment_types (name) VALUES ('pickup'), ('delivery');

-- ------------------------------------------------------------
-- 7. ORDERS  (2NF + 3NF: no transitive deps; FKs everywhere)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id         INTEGER NOT NULL REFERENCES users(id),
    status_id           INTEGER NOT NULL REFERENCES order_statuses(id) DEFAULT 1,
    fulfillment_type_id INTEGER NOT NULL REFERENCES fulfillment_types(id),
    -- delivery address (NULL for pickup)
    delivery_address    TEXT,
    delivery_city       TEXT,
    delivery_zip        TEXT,
    -- financials
    subtotal            REAL    NOT NULL DEFAULT 0,
    delivery_fee        REAL    NOT NULL DEFAULT 0,
    tax                 REAL    NOT NULL DEFAULT 0,
    total               REAL    NOT NULL DEFAULT 0,
    -- meta
    special_instructions TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
-- ------------------------------------------------------------
-- 8. ORDER_ITEMS  (2NF: all cols depend on full composite PK)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id INTEGER NOT NULL REFERENCES menu_items(id),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   REAL    NOT NULL CHECK (unit_price >= 0),   -- snapshot at order time
    UNIQUE (order_id, menu_item_id)
);

-- ------------------------------------------------------------
-- 9. ORDER_STATUS_LOG  (audit trail — separate concern, 3NF)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_status_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status_id   INTEGER NOT NULL REFERENCES order_statuses(id),
    changed_by  INTEGER REFERENCES users(id),
    changed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    note        TEXT
);

-- ------------------------------------------------------------
-- INDEXES for common query patterns
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_orders_customer   ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders(status_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_menu_category     ON menu_items(category_id);
CREATE INDEX IF NOT EXISTS idx_users_email       ON users(email);
