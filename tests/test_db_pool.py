"""Reaproveitamento de conexões PostgreSQL (economia de egress no Supabase)."""
import psycopg
import pytest
from psycopg.pq import TransactionStatus

import database

CONFIG = {'DATABASE_URL': 'postgresql://synthetic.example.test/db', 'DATABASE_SCHEMA': 'synthetic', 'DATABASE_SSLMODE': 'require'}


class FakeInfo:
    transaction_status = TransactionStatus.IDLE


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.info = FakeInfo()
        self.statements = []
        self.fail = False

    def execute(self, query, params=None):
        if self.fail:
            raise psycopg.OperationalError('synthetic dropped connection')
        self.statements.append(str(query))
        return FakeCursor()

    def close(self):
        self.closed = True


class FakeCursor:
    rowcount = 0

    def fetchone(self):
        return None


@pytest.fixture
def opened(monkeypatch):
    database.close_pool()
    made = []

    def fake_connect(*args, **kwargs):
        made.append(FakeConnection())
        return made[-1]
    monkeypatch.setattr('database.psycopg.connect', fake_connect)
    yield made
    database.close_pool()


def test_sequential_connections_reuse_one_session(opened):
    for _ in range(5):
        conn = database.connect(CONFIG)
        conn.execute('SELECT 1')
        conn.close()
    assert len(opened) == 1 and not opened[0].closed


def test_double_close_never_hands_the_same_session_to_two_borrowers(opened):
    first = database.connect(CONFIG)
    first.close()
    second = database.connect(CONFIG)
    first.close()  # um close repetido não pode devolver a conexão emprestada a "second"
    third = database.connect(CONFIG)
    assert second.connection is not third.connection
    with pytest.raises(psycopg.InterfaceError):
        first.execute('SELECT 1')
    second.close()
    third.close()


def test_open_transaction_or_broken_session_is_not_reused(opened):
    conn = database.connect(CONFIG)
    conn.connection.info.transaction_status = TransactionStatus.INTRANS
    conn.close()
    assert opened[0].closed
    conn = database.connect(CONFIG)
    opened[1].closed = True
    conn.close()
    database.connect(CONFIG).close()
    assert len(opened) == 3


def test_idle_session_is_checked_and_replaced_when_dropped(opened, monkeypatch):
    database.connect(CONFIG).close()
    clock = [database.time.monotonic() + database.POOL_PING_AFTER + 1]
    monkeypatch.setattr('database.time.monotonic', lambda: clock[0])
    opened[0].fail = True
    conn = database.connect(CONFIG)
    assert len(opened) == 2 and opened[0].closed and conn.connection is opened[1]
    conn.close()


def test_pool_keeps_a_bounded_number_of_idle_sessions(opened):
    leases = [database.connect(CONFIG) for _ in range(database.POOL_IDLE_MAX + 2)]
    for lease in leases:
        lease.close()
    assert sum(not c.closed for c in opened) == database.POOL_IDLE_MAX


def test_idle_limit_is_per_process_and_evicts_other_schemas(opened):
    # Um esquema por teste (CI) não pode acumular conexões ociosas sem fim.
    for n in range(database.POOL_IDLE_MAX * 3):
        database.connect({**CONFIG, 'DATABASE_SCHEMA': 'synthetic_%d' % n}).close()
    assert sum(not c.closed for c in opened) == database.POOL_IDLE_MAX
    assert sum(len(conns) for conns in database._pool.values()) == database.POOL_IDLE_MAX
    # O esquema mais recente continua reaproveitado.
    before = len(opened)
    database.connect({**CONFIG, 'DATABASE_SCHEMA': 'synthetic_%d' % (database.POOL_IDLE_MAX * 3 - 1)}).close()
    assert len(opened) == before
