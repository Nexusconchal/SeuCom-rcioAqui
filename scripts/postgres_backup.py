"""Consistent private-schema dump and an optional isolated restore drill.

No connection string or customer content is printed. PostgreSQL tools receive
credentials through their environment. Restore is restricted to an empty,
separate database whose name starts with restore_.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


def pg_environment(url):
    fields = conninfo_to_dict(url)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('PG'):
            env.pop(key)
    for field, name in [('host','PGHOST'),('port','PGPORT'),('dbname','PGDATABASE'),('user','PGUSER'),
                        ('password','PGPASSWORD'),('sslmode','PGSSLMODE'),('sslrootcert','PGSSLROOTCERT')]:
        if fields.get(field):
            env[name] = fields[field]
    return env


def run_tool(tool, args, url, *, output=None, source=None, docker_image=None):
    env = pg_environment(url)
    prefix = []
    if docker_image:
        if not re.fullmatch(r'postgres:[1-9][0-9]*', docker_image):
            raise ValueError('Use uma imagem oficial postgres com versão principal explícita.')
        prefix = ['docker','run','--rm','-i','--network','host']
        for name in ('PGHOST','PGPORT','PGDATABASE','PGUSER','PGPASSWORD','PGSSLMODE'):
            if name in env:
                prefix.extend(['-e',name])
        prefix.append(docker_image)
    try:
        result = subprocess.run(prefix+[tool]+args, env=env, stdin=source, stdout=output or subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Não foi possível executar as ferramentas PostgreSQL. Confira instalação, versão e conectividade.') from None
    if result.returncode:
        # stderr may contain operational credentials/hosts; never print it.
        raise RuntimeError('A ferramenta PostgreSQL falhou. Confira acesso, versão e permissões; o destino original foi preservado.')
    return result.stdout


def table_counts(conn, schema):
    tables = [r[0] for r in conn.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename',(schema,))]
    return {name:conn.execute(sql.SQL('SELECT COUNT(*) FROM {}.{}').format(sql.Identifier(schema),sql.Identifier(name))).fetchone()[0] for name in tables}


def backup(url, schema, destination, *, restore_url=None, record_success=False, docker_image=None):
    destination = Path(destination).resolve()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',schema):
        raise ValueError('Schema inválido.')
    manifest = destination.with_suffix(destination.suffix+'.json')
    if destination.exists() or manifest.exists():
        raise ValueError('O destino já existe. Escolha um arquivo novo.')
    if record_success and not restore_url:
        raise ValueError('Só é possível registrar um exercício depois de restaurar e conferir.')
    if restore_url:
        source_fields, target_fields = conninfo_to_dict(url), conninfo_to_dict(restore_url)
        # Require a different DB name even on a separate host. This deliberately
        # errs on the side of refusing a potentially destructive destination.
        if not target_fields.get('dbname','').startswith('restore_') or target_fields.get('dbname')==source_fields.get('dbname'):
            raise ValueError('Use outro banco vazio com nome iniciado por restore_. Nunca use o banco de produção como destino.')
        with psycopg.connect(restore_url,connect_timeout=10) as target:
            if target.execute("SELECT 1 FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') LIMIT 1").fetchone():
                raise ValueError('O banco de restauração precisa estar vazio.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    partial = destination.with_suffix(destination.suffix+'.partial')
    # O_EXCL prevents overwriting another job's partial file or a symlink.
    fd = os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    finished = False
    try:
        with os.fdopen(fd,'wb') as output:
            with psycopg.connect(url,autocommit=True,connect_timeout=10) as source:
                source.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                try:
                    snapshot = source.execute('SELECT pg_export_snapshot()').fetchone()[0]
                    counts = table_counts(source,schema)
                    if not counts:
                        raise ValueError('Nenhuma tabela encontrada no schema informado.')
                    run_tool('pg_dump',['--format=custom','--no-owner','--no-privileges','--schema='+schema,'--snapshot='+snapshot],url,output=output,docker_image=docker_image)
                finally:
                    source.execute('ROLLBACK')
        with partial.open('rb') as data:
            run_tool('pg_restore',['--list'],url,source=data,docker_image=docker_image)
        # Hard link is exclusive: a concurrently created destination is never
        # replaced. Both files are on the same filesystem.
        os.link(partial,destination)
        partial.unlink()
        finished = True
        with destination.open('rb') as data:
            digest = hashlib.file_digest(data,'sha256').hexdigest()
        result = dict(at=datetime.now(timezone.utc).isoformat(timespec='seconds'),schema=schema,
                      sha256=digest,bytes=destination.stat().st_size,tables=counts,restored=False)
        if restore_url:
            with destination.open('rb') as data:
                run_tool('pg_restore',['--no-owner','--no-privileges','--exit-on-error','--single-transaction','--dbname='+conninfo_to_dict(restore_url)['dbname']],restore_url,source=data,docker_image=docker_image)
            with psycopg.connect(restore_url,connect_timeout=10) as restored:
                if table_counts(restored,schema)!=counts:
                    raise RuntimeError('A contagem de tabelas restauradas não confere com o snapshot.')
            result['restored']=True
            if record_success:
                with psycopg.connect(url,connect_timeout=10) as source:
                    statement=sql.SQL('INSERT INTO {}.platform_settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value').format(sql.Identifier(schema))
                    source.execute(statement,('operations.restore_drill',json.dumps({k:result[k] for k in ('at','sha256','bytes','restored')})))
        with manifest.open('x',encoding='utf-8') as output:
            json.dump(result,output,ensure_ascii=False,indent=2)
        return result
    finally:
        if not finished and partial.exists():
            partial.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--schema',default=os.getenv('DATABASE_SCHEMA','seucomercio'))
    parser.add_argument('--restore-test',action='store_true',help='Usa RESTORE_TEST_DATABASE_URL, que deve apontar para outro banco vazio restore_.')
    parser.add_argument('--record-success',action='store_true')
    parser.add_argument('--docker-image',help='Opcional no CI Linux: postgres:17. Exige Docker e rede host.')
    args=parser.parse_args()
    url=os.getenv('DATABASE_URL','')
    restore_url=os.getenv('RESTORE_TEST_DATABASE_URL','') if args.restore_test else None
    if not url or args.restore_test and not restore_url:
        parser.error('Configure DATABASE_URL e, para o exercício, RESTORE_TEST_DATABASE_URL no ambiente seguro.')
    try:
        result=backup(url,args.schema,args.destination,restore_url=restore_url,record_success=args.record_success,docker_image=args.docker_image)
        print(json.dumps({k:result[k] for k in ('at','sha256','bytes','restored')}))
    except (ValueError,RuntimeError,psycopg.Error) as error:
        # psycopg errors may include SQL, host and username. Do not expose those.
        parser.exit(1, (str(error) if isinstance(error,(ValueError,RuntimeError)) else 'Não foi possível acessar o banco para backup/restauração.')+'\n')


if __name__=='__main__':
    main()
