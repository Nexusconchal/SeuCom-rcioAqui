SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='30s';
SET LOCAL ROLE seucomercio_backend;
SET LOCAL search_path TO seucomercio,public;

CREATE TABLE IF NOT EXISTS order_payment_attempts (
 id BIGSERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 order_id INTEGER NOT NULL REFERENCES orders(id), kind TEXT NOT NULL,
 attempt INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
 external_reference TEXT NOT NULL UNIQUE, collector_id TEXT NOT NULL, credential TEXT NOT NULL DEFAULT '',
 amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'creating',
 provider_id TEXT NOT NULL DEFAULT '', preference_id TEXT NOT NULL DEFAULT '',
 checkout_url TEXT NOT NULL DEFAULT '', pix_code TEXT NOT NULL DEFAULT '',
 expires_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(order_id,kind,attempt)
);
CREATE INDEX IF NOT EXISTS ix_order_payment_attempts_order ON order_payment_attempts(store_id,order_id,id);
CREATE TABLE IF NOT EXISTS order_payment_transactions (
 id BIGSERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 order_id INTEGER NOT NULL REFERENCES orders(id), attempt_id INTEGER NOT NULL REFERENCES order_payment_attempts(id),
 provider_id TEXT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL,
 refunded INTEGER NOT NULL DEFAULT 0, fee INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL, approved_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
 refund_key TEXT NOT NULL DEFAULT '', refund_state TEXT NOT NULL DEFAULT '', refund_started_at TEXT NOT NULL DEFAULT '',
 UNIQUE(store_id,provider_id)
);
CREATE INDEX IF NOT EXISTS ix_order_payment_transactions_order ON order_payment_transactions(store_id,order_id,id);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS payer_email TEXT NOT NULL DEFAULT '';
ALTER TABLE order_payment_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_payment_transactions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON order_payment_attempts,order_payment_transactions FROM PUBLIC,anon,authenticated;
REVOKE ALL ON SEQUENCE order_payment_attempts_id_seq,order_payment_transactions_id_seq FROM PUBLIC,anon,authenticated;
RESET ROLE;
