"""SQLite local e PostgreSQL para hospedagem sem disco persistente."""
import re
import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

BASE = Path(__file__).resolve().parent
SCHEMA_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor, inserted=False):
        self.cursor = cursor
        self.rowcount = cursor.rowcount
        self.lastrowid = cursor.fetchone()["id"] if inserted else None

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
            connect_timeout=10, prepare_threshold=None, row_factory=dict_row)
        self.connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        self.connection.execute("SET statement_timeout='20s'")
        self.connection.execute("SET lock_timeout='15s'")

    def execute(self, query, params=()):
        if query == "BEGIN IMMEDIATE":
            self.connection.execute("BEGIN")
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()))")
            return Cursor(self.connection.execute("SELECT 1"))
        insert = re.match(r"\s*INSERT INTO ([a-z_]+)", query, re.I)
        inserted = bool(insert and insert.group(1).lower() != "rate_limits")
        query = query.replace("%", "%%").replace("?", "%s")
        if inserted:
            query = query.rstrip().rstrip(";") + " RETURNING id"
        try:
            return Cursor(self.connection.execute(query, params or None), inserted)
        except psycopg.IntegrityError as error:
            raise sqlite3.IntegrityError("Restrição do banco de dados") from error

    def close(self):
        self.connection.close()


def connect(config):
    if config["DATABASE_URL"]:
        return Postgres(config)
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
        with psycopg.connect(config["DATABASE_URL"], autocommit=True, connect_timeout=10) as conn:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (schema,))
                exists = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone()
                if not exists:
                    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                conn.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema)))
                conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                for statement in (BASE / "schema.postgres.sql").read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        conn.execute(statement)
                tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s", (schema,)).fetchall()
                for (table,) in tables:
                    conn.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(table)))
                    conn.execute(sql.SQL("REVOKE ALL ON TABLE {} FROM PUBLIC").format(sql.Identifier(table)))
    else:
        Path(config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(config["DATABASE_PATH"]) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))
