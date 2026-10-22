"""Restore to an isolated, empty test database; never alter the source data."""
import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts.postgres_backup import backup
from tests.test_api import app, shop
from tests.test_growth import sql as query


def test_restore_guard_refuses_production_name_and_existing_files(tmp_path):
    url='postgresql://fake:fake@localhost/production'
    with pytest.raises(ValueError,match='restore_'):
        backup(url,'seucomercio',tmp_path/'private.dump',restore_url=url)
    destination=tmp_path/'existing.dump'
    destination.write_bytes(b'do not replace')
    with pytest.raises(ValueError,match='destino'):
        backup(url,'seucomercio',destination)
    assert destination.read_bytes()==b'do not replace'


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'),reason='Exige PostgreSQL de teste e ferramentas pg_dump/pg_restore')
def test_consistent_dump_restores_tables_data_and_records_success(shop,tmp_path):
    c,_=shop
    source=c.application.config['DATABASE_URL']
    schema=c.application.config['DATABASE_SCHEMA']
    target_name='restore_'+uuid.uuid4().hex
    options=conninfo_to_dict(source)
    options['dbname']=target_name
    target_url=make_conninfo(**options)
    with psycopg.connect(source,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target_name)))
    try:
        result=backup(source,schema,tmp_path/'private.dump',restore_url=target_url,record_success=True,
                      docker_image=os.getenv('PG_BACKUP_DOCKER_IMAGE'))
        assert result['restored'] is True and result['tables']['products']==1
        assert result['bytes']>1000 and len(result['sha256'])==64
        with psycopg.connect(target_url) as restored:
            assert restored.execute(sql.SQL('SELECT name FROM {}.products').format(sql.Identifier(schema))).fetchone()[0]=='Burger'
            assert restored.execute('SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s',(schema,'account_tokens')).fetchone()[0] is True
        assert query(c,"SELECT value FROM platform_settings WHERE key='operations.restore_drill'")
        assert query(c,'SELECT stock FROM products')[0]['stock']==5
        with pytest.raises(ValueError,match='vazio'):
            backup(source,schema,tmp_path/'another.dump',restore_url=target_url,docker_image=os.getenv('PG_BACKUP_DOCKER_IMAGE'))
    finally:
        with psycopg.connect(source,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target_name)))
