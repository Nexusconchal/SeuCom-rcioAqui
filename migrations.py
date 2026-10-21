"""Additive, repeatable upgrades for existing SQLite/PostgreSQL installations."""
ADDITIONS = {
    'users': {'platform_admin': 'INTEGER NOT NULL DEFAULT 0', 'last_login_at': 'TEXT', 'terms_accepted_at': 'TEXT'},
    'stores': {'commission_bps': 'INTEGER NOT NULL DEFAULT 0', 'monthly_fee': 'INTEGER NOT NULL DEFAULT 0',
               'payment_fees': "TEXT NOT NULL DEFAULT '{}'", 'default_delivery_cost': 'INTEGER',
               'enabled': 'INTEGER NOT NULL DEFAULT 1', 'hours': "TEXT NOT NULL DEFAULT '{}'",
               'auto_hours': 'INTEGER NOT NULL DEFAULT 0', 'delivery_zones': "TEXT NOT NULL DEFAULT '[]'",
               'blocked_reason': "TEXT NOT NULL DEFAULT ''", 'promo_fee': 'INTEGER',
               'promo_until': "TEXT NOT NULL DEFAULT ''", 'promo_label': "TEXT NOT NULL DEFAULT ''",
               'allow_scheduling': 'INTEGER NOT NULL DEFAULT 0', 'mp_token': "TEXT NOT NULL DEFAULT ''",
               'mp_account': "TEXT NOT NULL DEFAULT ''", 'mp_webhook_key': "TEXT NOT NULL DEFAULT ''",
               'loyalty_enabled': 'INTEGER NOT NULL DEFAULT 0', 'loyalty_goal': 'INTEGER NOT NULL DEFAULT 10',
               'loyalty_reward': 'INTEGER NOT NULL DEFAULT 1000', 'trial_until': "TEXT NOT NULL DEFAULT ''",
               'billing_exempt': 'INTEGER NOT NULL DEFAULT 0', 'sub_id': "TEXT NOT NULL DEFAULT ''", 'sub_status': "TEXT NOT NULL DEFAULT ''",
               'sub_payer_email': "TEXT NOT NULL DEFAULT ''", 'sub_next_payment': "TEXT NOT NULL DEFAULT ''",
               'sub_checked_at': "TEXT NOT NULL DEFAULT ''", 'sub_used_trial': 'INTEGER NOT NULL DEFAULT 0', 'paid_until': "TEXT NOT NULL DEFAULT ''",
               'motoja_url': "TEXT NOT NULL DEFAULT ''", 'motoja_key': "TEXT NOT NULL DEFAULT ''", 'motoja_auto': 'INTEGER NOT NULL DEFAULT 0',
               'sub_pix_id': "TEXT NOT NULL DEFAULT ''", 'sub_pix_code': "TEXT NOT NULL DEFAULT ''", 'sub_pix_expires': "TEXT NOT NULL DEFAULT ''",
               'motoja_trigger': "TEXT NOT NULL DEFAULT 'preparing'", 'wa_instance': "TEXT NOT NULL DEFAULT ''", 'wa_enabled': 'INTEGER NOT NULL DEFAULT 0'},
    'products': {'unit_cost': 'INTEGER', 'low_stock': 'INTEGER NOT NULL DEFAULT 5', 'option_groups': "TEXT NOT NULL DEFAULT '[]'", 'suggested': 'INTEGER NOT NULL DEFAULT 0'},
    'orders': {'delivery_cost': 'INTEGER', 'payment_fee': 'INTEGER', 'platform_fee': 'INTEGER NOT NULL DEFAULT 0',
               'source': "TEXT NOT NULL DEFAULT 'web'", 'zone': "TEXT NOT NULL DEFAULT ''",
               'scheduled_for': "TEXT NOT NULL DEFAULT ''", 'rating': 'INTEGER', 'review': "TEXT NOT NULL DEFAULT ''", 'reviewed_at': 'TEXT',
               'pix_provider_id': "TEXT NOT NULL DEFAULT ''", 'pix_code': "TEXT NOT NULL DEFAULT ''",
               'pix_expires': "TEXT NOT NULL DEFAULT ''", 'pix_checked_at': "TEXT NOT NULL DEFAULT ''", 'pix_attempts': 'INTEGER NOT NULL DEFAULT 0',
               'loyalty_discount': 'INTEGER NOT NULL DEFAULT 0', 'motoja_status': "TEXT NOT NULL DEFAULT ''",
               'motoja_delivery_id': "TEXT NOT NULL DEFAULT ''", 'motoja_info': "TEXT NOT NULL DEFAULT '{}'",
               'motoja_checked_at': "TEXT NOT NULL DEFAULT ''", 'wa_sent': "TEXT NOT NULL DEFAULT ''"},
    'coupons': {'first_order': 'INTEGER NOT NULL DEFAULT 0'},
    'order_items': {'unit_cost': 'INTEGER'},
    'expenses': {'category': "TEXT NOT NULL DEFAULT 'operating'"},
    'platform_ledger': {'idempotency_key': 'TEXT', 'payload_hash': 'TEXT', 'voided_at': 'TEXT'},
    'api_keys': {'deleted_at': 'TEXT'},
}

TABLES = """
CREATE TABLE IF NOT EXISTS ingredients (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL,
 unit TEXT NOT NULL CHECK(unit IN ('kg','l','un')), stock INTEGER NOT NULL CHECK(stock>=0),
 low_stock INTEGER NOT NULL DEFAULT 0, unit_cost INTEGER, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS recipes (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), product_id INTEGER NOT NULL REFERENCES products(id),
 ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 UNIQUE(product_id,ingredient_id)
);
CREATE TABLE IF NOT EXISTS ingredient_movements (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
 order_id INTEGER REFERENCES orders(id), delta INTEGER NOT NULL, balance INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_opt_ins (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), phone TEXT NOT NULL,
 consent INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, UNIQUE(store_id,phone)
);
CREATE TABLE IF NOT EXISTS shopping_sessions (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, cart_at TEXT, checkout_at TEXT, order_id INTEGER REFERENCES orders(id),
 items TEXT NOT NULL DEFAULT '[]', subtotal INTEGER NOT NULL DEFAULT 0, customer TEXT NOT NULL DEFAULT '',
 phone TEXT NOT NULL DEFAULT '', recovery_consent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS marketing_campaigns (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, segment TEXT NOT NULL,
 message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ingredients_store ON ingredients(store_id,active);
CREATE INDEX IF NOT EXISTS ix_recipes_store ON recipes(store_id,product_id);
CREATE INDEX IF NOT EXISTS ix_ingredient_movement_order ON ingredient_movements(order_id);
CREATE INDEX IF NOT EXISTS ix_ingredient_movement_store ON ingredient_movements(store_id,id);
CREATE INDEX IF NOT EXISTS ix_opt_ins_store ON customer_opt_ins(store_id,consent);
CREATE INDEX IF NOT EXISTS ix_shopping_store_date ON shopping_sessions(store_id,created_at);
CREATE INDEX IF NOT EXISTS ix_shopping_store_updated ON shopping_sessions(store_id,updated_at);
CREATE INDEX IF NOT EXISTS ix_campaigns_store ON marketing_campaigns(store_id,id);
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
CREATE TABLE IF NOT EXISTS store_members (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('manager','cashier','kitchen')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS push_subscriptions (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), user_id INTEGER NOT NULL REFERENCES users(id),
 endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL, auth TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_notices (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('info','promo','alert')),
 expires TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_messages (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), author_id INTEGER REFERENCES users(id),
 from_platform INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'chat', topic TEXT NOT NULL DEFAULT '',
 body TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_api_keys_store ON api_keys(store_id);
CREATE INDEX IF NOT EXISTS ix_support_store ON support_messages(store_id,id);
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


from operations import DDL as OPERATIONS_DDL
from merchandising import DDL as MERCHANDISING_DDL
from purchasing import DDL as PURCHASING_DDL
from campaign_queue import DDL as CAMPAIGN_DDL
from customer_segments import DDL as SEGMENTS_DDL
from cashback import DDL as CASHBACK_DDL
from inbox import DDL as INBOX_DDL
from credit import DDL as CREDIT_DDL
from store_network import DDL as NETWORK_DDL
from online_payments import DDL as ONLINE_PAYMENTS_DDL

TABLES += OPERATIONS_DDL + MERCHANDISING_DDL + PURCHASING_DDL
TABLES += CAMPAIGN_DDL
TABLES += SEGMENTS_DDL
TABLES += CASHBACK_DDL
TABLES += INBOX_DDL
TABLES += CREDIT_DDL
TABLES += NETWORK_DDL + ONLINE_PAYMENTS_DDL
TABLES += "CREATE UNIQUE INDEX IF NOT EXISTS ix_driver_gps ON drivers(gps_hash) WHERE gps_hash!='';"
ADDITIONS['stores'].update({'timezone': "TEXT NOT NULL DEFAULT 'America/Sao_Paulo'", 'auto_accept': 'INTEGER NOT NULL DEFAULT 0'})
ADDITIONS['stores'].update({'cashback_enabled': 'INTEGER NOT NULL DEFAULT 0', 'cashback_bps': 'INTEGER NOT NULL DEFAULT 500'})
ADDITIONS['orders'].update({'cashback_discount': 'INTEGER NOT NULL DEFAULT 0', 'cashback_earned': 'INTEGER NOT NULL DEFAULT 0'})
ADDITIONS['stores'].update({'inbox_hook_hash': "TEXT NOT NULL DEFAULT ''", 'inbox_bot': 'INTEGER NOT NULL DEFAULT 0'})
ADDITIONS['inbox_messages']={'media': "TEXT NOT NULL DEFAULT ''", 'media_data': "TEXT NOT NULL DEFAULT ''"}
ADDITIONS['obligations']={'order_id':'INTEGER REFERENCES orders(id)'}
ADDITIONS['orders'].update({'latitude':'REAL','longitude':'REAL'})
ADDITIONS['drivers']={'gps_hash':"TEXT NOT NULL DEFAULT ''",'gps_lat':'REAL','gps_lon':'REAL','gps_accuracy':'REAL','gps_at':'TEXT'}
ADDITIONS['stores'].update({'postal_zones':"TEXT NOT NULL DEFAULT '[]'"})
ADDITIONS['orders']['payer_email'] = "TEXT NOT NULL DEFAULT ''"
ADDITIONS['orders'].update({'postal_code':"TEXT NOT NULL DEFAULT ''"})
ADDITIONS['orders'].update({'route_position':'INTEGER NOT NULL DEFAULT 0'})
ADDITIONS['products'].update({'production_sector':"TEXT NOT NULL DEFAULT 'Cozinha'"})
ADDITIONS['order_items'].update({'production_sector':"TEXT NOT NULL DEFAULT 'Cozinha'",'kitchen_state':"TEXT NOT NULL DEFAULT 'new'"})
ADDITIONS['products']['suggestion_ids'] = "TEXT NOT NULL DEFAULT '[]'"
ADDITIONS['order_items'].update({'suggested_by': 'INTEGER', 'suggested_by_name': "TEXT NOT NULL DEFAULT ''"})
ADDITIONS['stores']['subscribed_at'] = "TEXT NOT NULL DEFAULT ''"
ADDITIONS['platform_ledger'].update({'paid_at': "TEXT NOT NULL DEFAULT ''", 'is_subscription': 'INTEGER NOT NULL DEFAULT 0'})


def upgrade(conn, postgres=False):
    kitchen_added=False
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
                kitchen_added=kitchen_added or (table=='order_items' and column=='kitchen_state')
    if kitchen_added:
        conn.execute("UPDATE order_items SET kitchen_state='ready' WHERE order_id IN (SELECT id FROM orders WHERE status IN ('ready','delivering','completed'))")
        conn.execute("UPDATE order_items SET kitchen_state='preparing' WHERE order_id IN (SELECT id FROM orders WHERE status='preparing')")
    for statement in statements.split(';'):
        if statement.strip() and not statement.strip().startswith('CREATE TABLE'):
            conn.execute(statement)


def postgres_ddl():
    """DDL for the managed deployment migration; run as the private schema owner."""
    # Create extension tables first, then add missing columns to older versions.
    statements = [s+';' for s in TABLES.replace('id INTEGER PRIMARY KEY', 'id BIGSERIAL PRIMARY KEY').split(';') if s.strip().startswith('CREATE TABLE')]
    for table, columns in ADDITIONS.items():
        for column, definition in columns.items():
            if table=='order_items' and column=='kitchen_state':
                statements.append("""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='order_items' AND column_name='kitchen_state') THEN
                    ALTER TABLE order_items ADD COLUMN kitchen_state TEXT NOT NULL DEFAULT 'new';
                    UPDATE order_items SET kitchen_state='ready' WHERE order_id IN (SELECT id FROM orders WHERE status IN ('ready','delivering','completed'));
                    UPDATE order_items SET kitchen_state='preparing' WHERE order_id IN (SELECT id FROM orders WHERE status='preparing');
                    END IF; END $$;""")
            else:
                statements.append(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition};')
    statements.extend(s+';' for s in TABLES.split(';') if s.strip() and not s.strip().startswith('CREATE TABLE'))
    for table in ('cash_sessions', 'cash_adjustments', 'order_receipts', 'dining_tables', 'dining_accounts', 'dining_orders',
                  'catalog_rules', 'option_recipes', 'suppliers', 'obligations', 'obligation_settlements', 'production_recipes', 'production_batches', 'marketing_jobs', 'customer_segments', 'wallet_challenges', 'wallet_sessions', 'cashback_movements', 'inbox_threads', 'inbox_messages', 'credit_accounts', 'store_networks', 'network_stores', 'network_invites', 'order_payment_attempts', 'order_payment_transactions'):
        statements.append(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY; REVOKE ALL ON {table} FROM PUBLIC,anon,authenticated;')
    for table in ('api_keys', 'delivery_links', 'integration_events', 'stock_movements', 'platform_ledger', 'audit_log', 'platform_notices', 'store_members', 'platform_settings', 'push_subscriptions', 'support_messages', 'ingredients', 'recipes', 'ingredient_movements', 'customer_opt_ins', 'shopping_sessions', 'marketing_campaigns'):
        statements.extend([f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;', f'REVOKE ALL ON {table} FROM PUBLIC,anon,authenticated;'])
    return '\n'.join(statements)
