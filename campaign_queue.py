"""Fila persistente de campanhas. Consentimento é conferido novamente antes do envio."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import click
from flask import abort, g, jsonify

from connectors import Evolution

DDL = """
CREATE TABLE IF NOT EXISTS marketing_jobs (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), campaign_id INTEGER NOT NULL REFERENCES marketing_campaigns(id),
 phone TEXT NOT NULL, message TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
 claimed_at TEXT, sent_at TEXT, provider_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 UNIQUE(campaign_id,phone)
);
CREATE INDEX IF NOT EXISTS ix_marketing_due ON marketing_jobs(status,due_at,store_id);
"""


def dispatcher(app, limit=20):
    from database import connect
    provider = app.extensions.get('evolution') or Evolution(app.config.get('EVOLUTION_API_URL',''),app.config.get('EVOLUTION_API_KEY',''))
    if not provider.ready:
        return {'sent':0,'cancelled':0,'uncertain':0,'configured':False}
    summary={'sent':0,'cancelled':0,'uncertain':0,'configured':True}
    conn=connect(app.config)
    try:
        stamp=datetime.now(timezone.utc)
        # Um processo morto pode ter enviado a mensagem antes de registrar o retorno. Nunca reenvie automaticamente.
        conn.execute("UPDATE marketing_jobs SET status='uncertain',error='Envio interrompido; confira no WhatsApp antes de qualquer nova tentativa.' WHERE status='processing' AND claimed_at<?",((stamp-timedelta(minutes=5)).isoformat(timespec='seconds'),))
        for _ in range(max(1,min(limit,100))):
            conn.execute('BEGIN IMMEDIATE')
            try:
                candidates=conn.execute("""SELECT j.*,s.wa_instance,s.wa_enabled,s.enabled FROM marketing_jobs j JOIN stores s ON s.id=j.store_id
                    WHERE j.status='queued' AND j.due_at<=? ORDER BY j.due_at,j.id LIMIT 100""",(stamp.isoformat(timespec='seconds'),)).fetchall()
                job=None
                for candidate in candidates:
                    consent=conn.execute('SELECT consent FROM customer_opt_ins WHERE store_id=? AND phone=?',(candidate['store_id'],candidate['phone'])).fetchone()
                    if not consent or not consent['consent']:
                        conn.execute("UPDATE marketing_jobs SET status='cancelled',error='Autorização cancelada pelo cliente.' WHERE id=?",(candidate['id'],));summary['cancelled']+=1
                        continue
                    if not candidate['wa_instance'] or not candidate['wa_enabled'] or not candidate['enabled']:
                        continue
                    attempts=conn.execute("SELECT COUNT(*) FROM marketing_jobs WHERE store_id=? AND claimed_at>=?",(candidate['store_id'],(stamp-timedelta(hours=1)).isoformat(timespec='seconds'))).fetchone()[0]
                    recent=conn.execute("SELECT id FROM marketing_jobs WHERE store_id=? AND phone=? AND status IN ('processing','sent','uncertain') AND claimed_at>=? LIMIT 1",(candidate['store_id'],candidate['phone'],(stamp-timedelta(days=7)).isoformat(timespec='seconds'))).fetchone()
                    if attempts>=60:
                        continue
                    if recent:
                        conn.execute("UPDATE marketing_jobs SET due_at=? WHERE id=?",((stamp+timedelta(days=7)).isoformat(timespec='seconds'),candidate['id']))
                        continue
                    job=dict(candidate)
                    conn.execute("UPDATE marketing_jobs SET status='processing',claimed_at=? WHERE id=?",(stamp.isoformat(timespec='seconds'),job['id']))
                    break
                conn.execute('COMMIT')
            except Exception:
                conn.execute('ROLLBACK');raise
            if not job:
                break
            # Nenhum segredo, telefone ou texto de campanha é escrito em logs.
            try:
                code,result=provider.send_text(job['wa_instance'],job['phone'],job['message'])
                if code not in (200,201):
                    raise RuntimeError('provider response')
                provider_id=str((result.get('key') or {}).get('id') or result.get('id') or '')[:200]
                conn.execute("UPDATE marketing_jobs SET status='sent',sent_at=?,provider_id=? WHERE id=? AND status='processing'",(datetime.now(timezone.utc).isoformat(timespec='seconds'),provider_id,job['id']))
                summary['sent']+=1
            except Exception:
                conn.execute("UPDATE marketing_jobs SET status='uncertain',error='Provedor não confirmou o resultado. Confira o histórico do WhatsApp.' WHERE id=? AND status='processing'",(job['id'],))
                summary['uncertain']+=1
        return summary
    finally:
        conn.close()


def register_campaign_queue(app,helpers):
    h=SimpleNamespace(**helpers)

    @app.get('/api/admin/marketing/queue')
    @h.owner
    def campaign_queue_list():
        sid=g.store['id']
        provider=app.extensions.get('evolution') or Evolution(app.config.get('EVOLUTION_API_URL',''),app.config.get('EVOLUTION_API_KEY',''))
        return jsonify(configured=provider.ready and bool(g.store['wa_instance']) and bool(g.store['wa_enabled']),
            counts=h.rows('SELECT status,COUNT(*) AS count FROM marketing_jobs WHERE store_id=? GROUP BY status',(sid,)),
            jobs=h.rows('SELECT j.*,c.name FROM marketing_jobs j JOIN marketing_campaigns c ON c.id=j.campaign_id WHERE j.store_id=? ORDER BY j.id DESC LIMIT 100',(sid,)))

    @app.post('/api/admin/marketing/campaigns/<int:cid>/queue')
    @h.owner
    def campaign_enqueue(cid):
        value=h.data()
        campaign=h.owned('marketing_campaigns',cid)
        provider=app.extensions.get('evolution') or Evolution(app.config.get('EVOLUTION_API_URL',''),app.config.get('EVOLUTION_API_KEY',''))
        if not provider.ready or not g.store['wa_instance'] or not g.store['wa_enabled']:
            abort(409,description='Configure e conecte o WhatsApp da loja para agendar envios reais.')
        try:
            due=datetime.fromisoformat(value.get('due_at',''))
            if due.tzinfo is None or due<datetime.now(timezone.utc)-timedelta(minutes=1) or due>datetime.now(timezone.utc)+timedelta(days=30):
                raise ValueError()
        except (ValueError,TypeError):
            abort(400,description='Escolha uma data de envio entre agora e os próximos 30 dias.')
        recipients=app.extensions['campaign_recipients'](campaign)
        with h.transaction() as conn:
            before=conn.execute('SELECT COUNT(*) FROM marketing_jobs WHERE campaign_id=?',(cid,)).fetchone()[0]
            for recipient in recipients:
                conn.execute('''INSERT INTO marketing_jobs(store_id,campaign_id,phone,message,due_at,created_at) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(campaign_id,phone) DO NOTHING''',(g.store['id'],cid,recipient['phone'],recipient['message'],due.astimezone(timezone.utc).isoformat(timespec='seconds'),h.now()))
            queued=conn.execute('SELECT COUNT(*) FROM marketing_jobs WHERE campaign_id=?',(cid,)).fetchone()[0]-before
        return jsonify(queued=queued,selected=len(recipients))

    @app.post('/api/admin/marketing/campaigns/<int:cid>/cancel-queue')
    @h.owner
    def campaign_cancel_queue(cid):
        h.owned('marketing_campaigns',cid)
        h.db().execute("UPDATE marketing_jobs SET status='cancelled',error='Envio cancelado pela loja.' WHERE store_id=? AND campaign_id=? AND status='queued'",(g.store['id'],cid))
        return jsonify(ok=True)

    @app.cli.command('marketing-dispatch')
    @click.option('--limit',default=20,type=click.IntRange(1,100))
    def marketing_dispatch(limit):
        """Processa uma rodada curta. Execute em worker/cron com o mesmo PostgreSQL da aplicação."""
        click.echo(json.dumps(dispatcher(app,limit),ensure_ascii=False))
