CREATE TABLE IF NOT EXISTS users (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, auth_version BIGINT NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
 id BIGSERIAL PRIMARY KEY, owner_id BIGINT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
 phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
 logo TEXT NOT NULL DEFAULT '', banner TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL DEFAULT '#103f42', open BIGINT NOT NULL DEFAULT 0,
 delivery_fee BIGINT NOT NULL DEFAULT 500, minimum_order BIGINT NOT NULL DEFAULT 0,
 delivery_minutes TEXT NOT NULL DEFAULT '30–40 min',
 pix_key TEXT NOT NULL DEFAULT '', payments TEXT NOT NULL DEFAULT '["pix","cash","card"]',
 created_at TEXT NOT NULL, UNIQUE(owner_id)
);
CREATE TABLE IF NOT EXISTS categories (
 id BIGSERIAL PRIMARY KEY, store_id BIGINT NOT NULL REFERENCES stores(id),
 name TEXT NOT NULL, position BIGINT NOT NULL DEFAULT 0,
 UNIQUE(store_id,name)
);
CREATE TABLE IF NOT EXISTS products (
 id BIGSERIAL PRIMARY KEY, store_id BIGINT NOT NULL REFERENCES stores(id),
 category_id BIGINT REFERENCES categories(id), name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', price BIGINT NOT NULL CHECK(price>=0),
 image TEXT NOT NULL DEFAULT '', active BIGINT NOT NULL DEFAULT 1,
 featured BIGINT NOT NULL DEFAULT 0, stock BIGINT CHECK(stock IS NULL OR stock>=0),
 extras TEXT NOT NULL DEFAULT '[]', position BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS drivers (
 id BIGSERIAL PRIMARY KEY, store_id BIGINT NOT NULL REFERENCES stores(id),
 name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', active BIGINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS coupons (
 id BIGSERIAL PRIMARY KEY, store_id BIGINT NOT NULL REFERENCES stores(id),
 code TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('percent','fixed')),
 value BIGINT NOT NULL CHECK(value>0), minimum BIGINT NOT NULL DEFAULT 0,
 expires TEXT NOT NULL DEFAULT '', max_uses BIGINT, uses BIGINT NOT NULL DEFAULT 0,
 active BIGINT NOT NULL DEFAULT 1, UNIQUE(store_id,code)
);
CREATE TABLE IF NOT EXISTS orders (
 id BIGSERIAL PRIMARY KEY, store_id BIGINT NOT NULL REFERENCES stores(id),
 number BIGINT NOT NULL, tracking_hash TEXT NOT NULL UNIQUE,
 customer TEXT NOT NULL, phone TEXT NOT NULL, mode TEXT NOT NULL,
 address TEXT NOT NULL DEFAULT '', payment TEXT NOT NULL, change_for BIGINT,
 notes TEXT NOT NULL DEFAULT '', subtotal BIGINT NOT NULL, discount BIGINT NOT NULL DEFAULT 0,
 delivery_fee BIGINT NOT NULL DEFAULT 0, total BIGINT NOT NULL, coupon_id BIGINT REFERENCES coupons(id),
 status TEXT NOT NULL DEFAULT 'new', paid BIGINT NOT NULL DEFAULT 0,
 driver_id BIGINT REFERENCES drivers(id), idempotency_key TEXT NOT NULL,
 payload_hash TEXT NOT NULL, tracking_token TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(store_id,number), UNIQUE(store_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS order_items (
 id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id),
 product_id BIGINT NOT NULL REFERENCES products(id), name TEXT NOT NULL,
 quantity BIGINT NOT NULL CHECK(quantity>0), unit_price BIGINT NOT NULL,
 extras TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS order_events (
 id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expenses (
 id BIGSERIAL PRIMARY KEY, store_id BIGINT NOT NULL REFERENCES stores(id),
 description TEXT NOT NULL, amount BIGINT NOT NULL CHECK(amount>0), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limits (
 key TEXT PRIMARY KEY, count BIGINT NOT NULL, resets_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_orders_store_date ON orders(store_id,created_at);
CREATE INDEX IF NOT EXISTS ix_orders_store_status ON orders(store_id,status);
CREATE INDEX IF NOT EXISTS ix_products_store ON products(store_id);
