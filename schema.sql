PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, auth_version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
 phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
 logo TEXT NOT NULL DEFAULT '', banner TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL DEFAULT '#103f42', open INTEGER NOT NULL DEFAULT 0,
 delivery_fee INTEGER NOT NULL DEFAULT 500, minimum_order INTEGER NOT NULL DEFAULT 0,
 delivery_minutes TEXT NOT NULL DEFAULT '30–40 min',
 pix_key TEXT NOT NULL DEFAULT '', payments TEXT NOT NULL DEFAULT '["pix","cash","card"]',
 created_at TEXT NOT NULL, UNIQUE(owner_id)
);
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0,
 UNIQUE(store_id,name)
);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 category_id INTEGER REFERENCES categories(id), name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL CHECK(price>=0),
 image TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
 featured INTEGER NOT NULL DEFAULT 0, stock INTEGER CHECK(stock IS NULL OR stock>=0),
 extras TEXT NOT NULL DEFAULT '[]', position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS drivers (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS coupons (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 code TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('percent','fixed')),
 value INTEGER NOT NULL CHECK(value>0), minimum INTEGER NOT NULL DEFAULT 0,
 expires TEXT NOT NULL DEFAULT '', max_uses INTEGER, uses INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1, UNIQUE(store_id,code)
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 number INTEGER NOT NULL, tracking_hash TEXT NOT NULL UNIQUE,
 customer TEXT NOT NULL, phone TEXT NOT NULL, mode TEXT NOT NULL,
 address TEXT NOT NULL DEFAULT '', payment TEXT NOT NULL, change_for INTEGER,
 notes TEXT NOT NULL DEFAULT '', subtotal INTEGER NOT NULL, discount INTEGER NOT NULL DEFAULT 0,
 delivery_fee INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL, coupon_id INTEGER REFERENCES coupons(id),
 status TEXT NOT NULL DEFAULT 'new', paid INTEGER NOT NULL DEFAULT 0,
 driver_id INTEGER REFERENCES drivers(id), idempotency_key TEXT NOT NULL,
 payload_hash TEXT NOT NULL, tracking_token TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(store_id,number), UNIQUE(store_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS order_items (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 product_id INTEGER NOT NULL REFERENCES products(id), name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>0), unit_price INTEGER NOT NULL,
 extras TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS order_events (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expenses (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 description TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limits (
 key TEXT PRIMARY KEY, count INTEGER NOT NULL, resets_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_orders_store_date ON orders(store_id,created_at);
CREATE INDEX IF NOT EXISTS ix_orders_store_status ON orders(store_id,status);
CREATE INDEX IF NOT EXISTS ix_products_store ON products(store_id);
