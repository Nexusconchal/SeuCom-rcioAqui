"""Additive, repeatable upgrades for existing SQLite/PostgreSQL installations."""
ADDITIONS = {
    'users': {'platform_admin': 'INTEGER NOT NULL DEFAULT 0'},
    'stores': {'commission_bps': 'INTEGER NOT NULL DEFAULT 0', 'monthly_fee': 'INTEGER NOT NULL DEFAULT 0',
               'payment_fees': "TEXT NOT NULL DEFAULT '{}'", 'default_delivery_cost': 'INTEGER',
               'enabled': 'INTEGER NOT NULL DEFAULT 1', 'hours': "TEXT NOT NULL DEFAULT '{}'",
               'auto_hours': 'INTEGER NOT NULL DEFAULT 0', 'delivery_zones': "TEXT NOT NULL DEFAULT '[]'",
               'blocked_reason': "TEXT NOT NULL DEFAULT ''", 'promo_fee': 'INTEGER',
               'promo_until': "TEXT NOT NULL DEFAULT ''", 'promo_label': "TEXT NOT NULL DEFAULT ''",
               'allow_scheduling': 'INTEGER NOT NULL DEFAULT 0'},
    'products': {'unit_cost': 'INTEGER', 'low_stock': 'INTEGER NOT NULL DEFAULT 5', 'option_groups': "TEXT NOT NULL DEFAULT '[]'"},
    'orders': {'delivery_cost': 'INTEGER', 'payment_fee': 'INTEGER', 'platform_fee': 'INTEGER NOT NULL DEFAULT 0',
               'source': "TEXT NOT NULL DEFAULT 'web'", 'zone': "TEXT NOT NULL DEFAULT ''",
               'scheduled_for': "TEXT NOT NULL DEFAULT ''", 'rating': 'INTEGER', 'review': "TEXT NOT NULL DEFAULT ''", 'reviewed_at': 'TEXT'},
    'order_items': {'unit_cost': 'INTEGER'},
    'expenses': {'category': "TEXT NOT NULL DEFAULT 'operating'"},
    'platform_ledger': {'idempotency_key': 'TEXT', 'payload_hash': 'TEXT', 'voided_at': 'TEXT'},
    'api_keys': {'deleted_at': 'TEXT'},
}

TABLES = """
CREATE TABLE IF NOT EXISTS api_keys (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL, scopes TEXT NOT NULL,
 created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS delivery_links (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id), key_id INTEGER NOT NULL REFERENCES api_keys(id),
 external_id TEXT NOT NULL, provider TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'claimed',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(store_id,provider,external_id)
);
CREATE TABLE IF NOT EXISTS integration_events (
 id INTEGER PRIMARY KEY, key_id INTEGER NOT NULL REFERENCES api_keys(id), order_id INTEGER NOT NULL REFERENCES orders(id),
 event_id TEXT NOT NULL, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(key_id,event_id)
);
CREATE TABLE IF NOT EXISTS stock_movements (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), product_id INTEGER NOT NULL REFERENCES products(id),
 delta INTEGER NOT NULL, balance INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_ledger (
 id INTEGER PRIMARY KEY, store_id INTEGER REFERENCES stores(id), kind TEXT NOT NULL CHECK(kind IN ('receipt','expense')),
 description TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), created_at TEXT NOT NULL,
 idempotency_key TEXT UNIQUE, payload_hash TEXT, voided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), store_id INTEGER REFERENCES stores(id),
 action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_notices (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('info','promo','alert')),
 expires TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_api_keys_store ON api_keys(store_id);
CREATE INDEX IF NOT EXISTS ix_delivery_store ON delivery_links(store_id,updated_at);
CREATE INDEX IF NOT EXISTS ix_delivery_key ON delivery_links(key_id);
CREATE INDEX IF NOT EXISTS ix_integration_event_order ON integration_events(order_id);
CREATE INDEX IF NOT EXISTS ix_stock_store ON stock_movements(store_id,created_at);
CREATE INDEX IF NOT EXISTS ix_stock_product ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS ix_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS ix_platform_ledger_date ON platform_ledger(created_at);
CREATE INDEX IF NOT EXISTS ix_platform_ledger_store ON platform_ledger(store_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_platform_ledger_idempotency ON platform_ledger(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_audit_store ON audit_log(store_id,created_at);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_log(actor_id);
"""


def upgrade(conn, postgres=False):
    statements = TABLES.replace('id INTEGER PRIMARY KEY', 'id BIGSERIAL PRIMARY KEY') if postgres else TABLES
    for statement in statements.split(';'):
        if statement.strip().startswith('CREATE TABLE'):
            conn.execute(statement)
    for table, columns in ADDITIONS.items():
        existing = ({r[0] for r in conn.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s', (table,)).fetchall()}
                    if postgres else {r[1] for r in conn.execute(f'PRAGMA table_info({table})')})
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    for statement in statements.split(';'):
        if statement.strip() and not statement.strip().startswith('CREATE TABLE'):
            conn.execute(statement)


def postgres_ddl():
    """DDL for the managed deployment migration; run as the private schema owner."""
    # Create extension tables first, then add missing columns to older versions.
    statements = [s+';' for s in TABLES.replace('id INTEGER PRIMARY KEY', 'id BIGSERIAL PRIMARY KEY').split(';') if s.strip().startswith('CREATE TABLE')]
    for table, columns in ADDITIONS.items():
        for column, definition in columns.items():
            statements.append(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition};')
    statements.extend(s+';' for s in TABLES.split(';') if s.strip() and not s.strip().startswith('CREATE TABLE'))
    for table in ('api_keys', 'delivery_links', 'integration_events', 'stock_movements', 'platform_ledger', 'audit_log', 'platform_notices'):
        statements.extend([f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;', f'REVOKE ALL ON {table} FROM PUBLIC,anon,authenticated;'])
    return '\n'.join(statements)
