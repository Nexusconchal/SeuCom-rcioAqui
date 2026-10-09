"""Valida o mesmo usuário restrito usado na hospedagem, sem superusuário."""
import os
import secrets
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from database import connect, initialize

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Exige PostgreSQL de teste")
def test_private_schema_with_restricted_backend_role():
    url = os.environ["TEST_DATABASE_URL"]
    role = "backend_" + uuid.uuid4().hex
    schema = "private_" + uuid.uuid4().hex
    outsider = "outsider_" + uuid.uuid4().hex
    password = secrets.token_hex(32)
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
        admin.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(outsider)))
        admin.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(sql.Identifier(schema), sql.Identifier(role)))
        try:
            parameters = conninfo_to_dict(url)
            parameters.update(user=role, password=password)
            config = {"DATABASE_URL": make_conninfo(**parameters), "DATABASE_SCHEMA": schema}
            initialize(config)
            connection = connect(config)
            try:
                connection.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                    ("Test", "private@example.test", "test-hash", "2026-10-09T00:00:00+00:00"))
                assert connection.execute("SELECT name FROM users").fetchone()["name"] == "Test"
            finally:
                connection.close()
            admin.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(outsider)))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin.execute(sql.SQL("SELECT * FROM {}.users").format(sql.Identifier(schema)))
            admin.execute("RESET ROLE")
            security = admin.execute("SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='users'", (schema,)).fetchone()
            assert security[0] is True
        finally:
            admin.execute("RESET ROLE")
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(outsider)))
