"""SQLite local e PostgreSQL para hospedagem sem disco persistente."""
import re
import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from migrations import upgrade

BASE = Path(__file__).resolve().parent
SCHEMA_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")


def tls_options(config):
    mode=config.get('DATABASE_SSLMODE','')
    if mode and mode not in ('require','verify-ca','verify-full'):
        raise ValueError('DATABASE_SSLMODE inválido. Use TLS ou deixe vazio somente no desenvolvimento.')
    return {'sslmode':mode} if mode else {}


class Row(dict):
    def __init__(self, values):
        # PostgreSQL SUM(bigint) returns numeric. Keep integer-centavo/count
        # results numeric in JSON, matching SQLite without truncating fractions.
        super().__init__((key, int(value) if isinstance(value, Decimal) and value == value.to_integral_value() else value)
                         for key, value in values.items())

    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor, inserted=False):
        self.cursor = cursor
        self.rowcount = cursor.rowcount
        returned=cursor.fetchone() if inserted else None
        self.lastrowid = returned['id'] if returned is not None else None

    def fetchone(self):
        value = self.cursor.fetchone()
        return Row(value) if value is not None else None

    def fetchall(self):
        return [Row(value) for value in self.cursor.fetchall()]

    def __iter__(self):
        for value in self.cursor:
            yield Row(value)


class Postgres:
    def __init__(self, config):
        schema = config["DATABASE_SCHEMA"]
        if not SCHEMA_NAME.fullmatch(schema):
            raise ValueError("DATABASE_SCHEMA inválido.")
        self.connection = psycopg.connect(config["DATABASE_URL"], autocommit=True,
            connect_timeout=10, prepare_threshold=None, row_factory=dict_row,**tls_options(config))
        self.connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        self.connection.execute("SET statement_timeout='20s'")
        self.connection.execute("SET lock_timeout='15s'")

    def execute(self, query, params=()):
        if query == "BEGIN IMMEDIATE":
            self.connection.execute("BEGIN")
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()))")
            return Cursor(self.connection.execute("SELECT 1"))
        insert = re.match(r"\s*INSERT INTO ([a-z_]+)", query, re.I)
        # Tabelas sem coluna id não podem usar RETURNING id.
        inserted = bool(insert and insert.group(1).lower() not in ("rate_limits", "platform_settings"))
        query = query.replace("%", "%%").replace("?", "%s")
        if inserted:
            query = query.rstrip().rstrip(";") + " RETURNING id"
        try:
            return Cursor(self.connection.execute(query, params or None), inserted)
        except psycopg.IntegrityError as error:
            raise sqlite3.IntegrityError("Restrição do banco de dados") from error

    def close(self):
        self.connection.close()


# Reaproveita conexões PostgreSQL entre requisições e rodadas do robô.
# Abrir uma conexão nova custa handshake TLS, autenticação e três SETs no
# pooler do Supabase; com o loop do WhatsApp isso passava de 80 mil conexões
# por dia e estourou a cota de egress do plano gratuito.
POOL_IDLE_MAX = 4          # conexões ociosas guardadas por processo
POOL_PING_AFTER = 60       # segundos parada antes de conferir com SELECT 1
POOL_MAX_AGE = 1800        # renova a conexão a cada 30 minutos
_pool = {}
_pool_lock = threading.Lock()


def _pool_key(config):
    return (config["DATABASE_URL"], config["DATABASE_SCHEMA"], config.get("DATABASE_SSLMODE", ""))


class Lease:
    """Empréstimo de uma conexão do pool; fechar devolve (uma única vez)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=()):
        if self._conn is None:
            raise psycopg.InterfaceError("Conexão já devolvida ao pool.")
        return self._conn.execute(query, params)

    @property
    def connection(self):
        return self._conn.connection if self._conn is not None else None

    def close(self):
        conn, self._conn = self._conn, None
        if conn is not None and not _release(conn):
            _discard(conn)


def _release(conn):
    """Devolve ao pool uma conexão saudável e sem transação aberta."""
    raw = conn.connection
    now = time.monotonic()
    if raw.closed or raw.info.transaction_status != TransactionStatus.IDLE or now - conn._born > POOL_MAX_AGE:
        return False
    evicted = None
    with _pool_lock:
        idle = _pool.setdefault(conn._pool_key, [])
        if len(idle) >= POOL_IDLE_MAX:
            return False
        # O limite vale para o processo inteiro: conexões de outro banco/esquema
        # (ex.: um esquema por teste) não podem ficar abertas para sempre.
        if sum(len(conns) for conns in _pool.values()) >= POOL_IDLE_MAX:
            others = [(c._last_used, key, c) for key, conns in _pool.items() if key != conn._pool_key for c in conns]
            if not others:
                return False
            _, key, evicted = min(others, key=lambda item: item[0])
            _pool[key].remove(evicted)
            if not _pool[key]:
                del _pool[key]
        conn._last_used = now
        idle.append(conn)
    if evicted is not None:
        _discard(evicted)
    return True


def _borrow(config):
    key = _pool_key(config)
    while True:
        with _pool_lock:
            idle = _pool.get(key)
            conn = idle.pop() if idle else None
        if conn is None:
            conn = Postgres(config)
            conn._pool_key, conn._born = key, time.monotonic()
            return Lease(conn)
        now = time.monotonic()
        if conn.connection.closed or now - conn._born > POOL_MAX_AGE:
            _discard(conn)
            continue
        if now - conn._last_used > POOL_PING_AFTER:
            try:
                conn.connection.execute("SELECT 1")
            except psycopg.Error:
                _discard(conn)
                continue
        return Lease(conn)


def _discard(conn):
    try:
        conn.connection.close()
    except Exception:
        pass


def close_pool():
    """Fecha as conexões ociosas (testes e encerramento do processo)."""
    with _pool_lock:
        idle = [conn for conns in _pool.values() for conn in conns]
        _pool.clear()
    for conn in idle:
        _discard(conn)


def connect(config):
    if config["DATABASE_URL"]:
        return _borrow(config)
    connection = sqlite3.connect(config["DATABASE_PATH"], timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def initialize(config):
    if config["DATABASE_URL"]:
        schema = config["DATABASE_SCHEMA"]
        if not SCHEMA_NAME.fullmatch(schema):
            raise ValueError("DATABASE_SCHEMA inválido.")
        with psycopg.connect(config["DATABASE_URL"], autocommit=True, connect_timeout=10,**tls_options(config)) as conn:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (schema,))
                exists = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone()
                if not exists:
                    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                conn.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema)))
                client_roles=[role for role in ('anon','authenticated') if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone()]
                for role in client_roles:
                    conn.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM {}').format(sql.Identifier(schema),sql.Identifier(role)))
                conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                for statement in (BASE / "schema.postgres.sql").read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        conn.execute(statement)
                upgrade(conn, postgres=True)
                tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s", (schema,)).fetchall()
                for (table,) in tables:
                    conn.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(table)))
                    conn.execute(sql.SQL("REVOKE ALL ON TABLE {} FROM PUBLIC").format(sql.Identifier(table)))
                    for role in client_roles:
                        conn.execute(sql.SQL('REVOKE ALL ON TABLE {} FROM {}').format(sql.Identifier(table),sql.Identifier(role)))
    else:
        Path(config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(config["DATABASE_PATH"]) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))
            upgrade(conn)
