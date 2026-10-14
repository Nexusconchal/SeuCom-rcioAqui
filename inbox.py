"""Conversas de WhatsApp, atendimento humano e respostas por palavra-chave."""
import hashlib
import json
import re
import secrets
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import click
from flask import abort,g,jsonify,request

from connectors import Evolution

DDL="""
CREATE TABLE IF NOT EXISTS inbox_threads (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), phone TEXT NOT NULL, name TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'open', assigned_to INTEGER REFERENCES users(id), unread INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL, last_auto_at TEXT, UNIQUE(store_id,phone)
);
CREATE TABLE IF NOT EXISTS inbox_messages (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), thread_id INTEGER NOT NULL REFERENCES inbox_threads(id),
 direction TEXT NOT NULL CHECK(direction IN ('in','out')), body TEXT NOT NULL, external_id TEXT NOT NULL,
 status TEXT NOT NULL, automated INTEGER NOT NULL DEFAULT 0, actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL, claimed_at TEXT, sent_at TEXT, payload_hash TEXT NOT NULL DEFAULT '', UNIQUE(store_id,external_id)
);
CREATE INDEX IF NOT EXISTS ix_inbox_thread ON inbox_messages(thread_id,id);
CREATE INDEX IF NOT EXISTS ix_inbox_queue ON inbox_messages(status,id);
"""


def dispatch_inbox(app,limit=20):
    from database import connect
    provider=app.extensions.get('evolution') or Evolution(app.config.get('EVOLUTION_API_URL',''),app.config.get('EVOLUTION_API_KEY',''))
    if not provider.ready:return {'sent':0,'uncertain':0,'configured':False}
    result={'sent':0,'uncertain':0,'configured':True};conn=connect(app.config)
    try:
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        conn.execute("UPDATE inbox_messages SET status='uncertain' WHERE status='processing' AND claimed_at<?",((datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec='seconds'),))
        for _ in range(max(1,min(limit,100))):
            conn.execute('BEGIN IMMEDIATE')
            try:
                row=conn.execute("""SELECT m.*,t.phone,s.wa_instance FROM inbox_messages m JOIN inbox_threads t ON t.id=m.thread_id
                    JOIN stores s ON s.id=m.store_id WHERE m.status='queued' AND s.enabled=1 AND s.wa_instance!=''
                    AND (m.automated=0 OR (t.assigned_to IS NULL AND t.state='open' AND s.inbox_bot=1)) ORDER BY m.id LIMIT 1""").fetchone()
                if not row:conn.commit();break
                conn.execute("UPDATE inbox_messages SET status='processing',claimed_at=? WHERE id=?",(now,row['id']))
                conn.commit()
            except Exception:conn.rollback();raise
            try:
                code,_=provider.send_text(row['wa_instance'],row['phone'],row['body'])
                if code not in (200,201):raise RuntimeError('not confirmed')
                conn.execute("UPDATE inbox_messages SET status='sent',sent_at=? WHERE id=? AND status='processing'",(now,row['id']))
                result['sent']+=1
            except Exception:
                conn.execute("UPDATE inbox_messages SET status='uncertain' WHERE id=? AND status='processing'",(row['id'],))
                result['uncertain']+=1
        return result
    finally:conn.close()


def register_inbox(app,helpers):
    h=SimpleNamespace(**helpers)
    def provider():return app.extensions.get('evolution') or Evolution(app.config.get('EVOLUTION_API_URL',''),app.config.get('EVOLUTION_API_KEY',''))

    @app.post('/api/admin/inbox/connect')
    @h.owner
    def inbox_connect():
        if g.role!='owner':abort(403)
        if not g.store['wa_instance'] or not provider().ready:
            abort(409,description='Conecte o WhatsApp da loja primeiro.')
        base=app.config['PUBLIC_URL'] or request.host_url.rstrip('/')
        if not app.config['TESTING'] and not base.startswith('https://'):
            abort(409,description='Configure o endereço público HTTPS da aplicação.')
        token=secrets.token_urlsafe(32);url=base+'/webhooks/inbox/'+str(g.store['id'])
        code,_=provider().set_webhook(g.store['wa_instance'],url,token)
        if code not in (200,201):abort(502,description='A Evolution API não confirmou a configuração do atendimento.')
        h.db().execute('UPDATE stores SET inbox_hook_hash=? WHERE id=?',(hashlib.sha256(token.encode()).hexdigest(),g.store['id']))
        return jsonify(ok=True)

    @app.post('/webhooks/inbox/<int:sid>')
    def inbox_webhook(sid):
        s=h.one('SELECT * FROM stores WHERE id=?',(sid,))
        token=request.headers.get('X-Webhook-Token','')
        if not s or not s['inbox_hook_hash'] or not token or not secrets.compare_digest(s['inbox_hook_hash'],hashlib.sha256(token.encode()).hexdigest()):abort(401)
        h.limited('inbox-hook:'+str(sid),600,60)
        value=h.data()
        if value.get('instance')!=s['wa_instance']:abort(403)
        if value.get('event','').lower().replace('_','.')!='messages.upsert':return jsonify(ignored=True)
        message=value.get('data')
        if not isinstance(message,dict):abort(400)
        key=message.get('key') or {};jid=key.get('remoteJid','')
        if jid.endswith('@lid'):jid=key.get('remoteJidAlt','')
        if key.get('fromMe') or not re.fullmatch(r'55\d{10,11}@s.whatsapp.net',jid):return jsonify(ignored=True)
        phone=jid.split('@')[0][2:];eid=key.get('id')
        if not isinstance(eid,str) or not 1<=len(eid)<=200:abort(400)
        content=message.get('message') or {}
        body=content.get('conversation') or (content.get('extendedTextMessage') or {}).get('text') or '[Mensagem de mídia: confira no WhatsApp]'
        if not isinstance(body,str):abort(400)
        body=body[:4000];name=str(message.get('pushName') or phone)[:100];stamp=h.now()
        with h.transaction() as conn:
            if conn.execute('SELECT id FROM inbox_messages WHERE store_id=? AND external_id=?',(sid,'in:'+eid)).fetchone():return jsonify(ok=True,duplicate=True)
            conn.execute('''INSERT INTO inbox_threads(store_id,phone,name,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(store_id,phone) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at''',(sid,phone,name,stamp))
            thread=conn.execute('SELECT * FROM inbox_threads WHERE store_id=? AND phone=?',(sid,phone)).fetchone()
            conn.execute("UPDATE inbox_threads SET unread=unread+1,state=CASE WHEN state='closed' THEN 'open' ELSE state END WHERE id=?",(thread['id'],))
            conn.execute("INSERT INTO inbox_messages(store_id,thread_id,direction,body,external_id,status,created_at) VALUES(?,?,'in',?,?,'received',?)",(sid,thread['id'],body,'in:'+eid,stamp))
            normalized=body.casefold().strip();reply=''
            if normalized in ('humano','atendente','falar com atendente'):
                conn.execute("UPDATE inbox_threads SET state='human' WHERE id=?",(thread['id'],))
                conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE thread_id=? AND automated=1 AND status='queued'",(thread['id'],))
            elif s['inbox_bot'] and not thread['assigned_to'] and thread['state'] in ('open','closed') and (not thread['last_auto_at'] or thread['last_auto_at']<(datetime.now(timezone.utc)-timedelta(seconds=30)).isoformat(timespec='seconds')):
                base=app.config['PUBLIC_URL'] or request.host_url.rstrip('/')
                if normalized in ('menu','cardápio','cardapio','oi','olá','ola'):
                    reply=f"Olá! Veja o cardápio da {s['name']}: {base}/loja/{s['slug']}\nPara falar com a equipe, escreva ATENDENTE."
                elif normalized in ('horário','horario','horarios','horários'):
                    from app import store_status
                    reply=f"{s['name']}: {store_status(s)[1]}. Veja os horários e opções de agendamento: {base}/loja/{s['slug']}"
                if reply:
                    conn.execute("INSERT INTO inbox_messages(store_id,thread_id,direction,body,external_id,status,automated,created_at) VALUES(?,?,'out',?,?,'queued',1,?)",(sid,thread['id'],reply,'auto:'+eid,stamp))
                    conn.execute('UPDATE inbox_threads SET last_auto_at=? WHERE id=?',(stamp,thread['id']))
        return jsonify(ok=True)

    @app.get('/api/admin/inbox')
    @h.owner
    def inbox_list():
        return jsonify(configured=bool(g.store['inbox_hook_hash']),available=provider().ready and bool(g.store['wa_instance']),bot=bool(g.store['inbox_bot']),
            threads=h.rows('SELECT t.*,u.name AS assigned_name FROM inbox_threads t LEFT JOIN users u ON u.id=t.assigned_to WHERE t.store_id=? ORDER BY t.updated_at DESC LIMIT 200',(g.store['id'],)))

    @app.get('/api/admin/inbox/<int:tid>')
    @h.owner
    def inbox_thread(tid):
        thread=h.owned('inbox_threads',tid)
        h.db().execute('UPDATE inbox_threads SET unread=0 WHERE id=?',(tid,))
        return jsonify(thread={**dict(thread),'mine':thread['assigned_to']==g.user['id']},messages=h.rows('SELECT id,direction,body,status,automated,created_at FROM inbox_messages WHERE thread_id=? ORDER BY id DESC LIMIT 100',(tid,)))

    @app.post('/api/admin/inbox/<int:tid>/claim')
    @h.owner
    def inbox_claim(tid):
        value=h.data()
        with h.transaction() as conn:
            thread=h.owned('inbox_threads',tid);claim=h.boolean(value,'claim',True)
            if thread['assigned_to'] and thread['assigned_to']!=g.user['id'] and g.role not in ('owner','manager'):abort(409,description='Esta conversa já está com outro atendente.')
            conn.execute('UPDATE inbox_threads SET assigned_to=?,state=?,updated_at=? WHERE id=?',(g.user['id'] if claim else None,'human' if claim else 'open',h.now(),tid))
            if claim:conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE thread_id=? AND automated=1 AND status='queued'",(tid,))
        return jsonify(ok=True)

    @app.post('/api/admin/inbox/<int:tid>/reply')
    @h.owner
    def inbox_reply(tid):
        value=h.data();body=h.text(value,'message',1,4000);key=request.headers.get('Idempotency-Key','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',key):abort(400,description='Identificador da mensagem inválido.')
        digest=hashlib.sha256(json.dumps([tid,body]).encode()).hexdigest()
        if not provider().ready or not g.store['wa_instance']:abort(409,description='Conecte o WhatsApp antes de responder.')
        with h.transaction() as conn:
            thread=h.owned('inbox_threads',tid)
            prior=conn.execute('SELECT * FROM inbox_messages WHERE store_id=? AND external_id=?',(g.store['id'],'out:'+key)).fetchone()
            if prior:
                if prior['payload_hash']!=digest:abort(409,description='Este identificador pertence a outra mensagem.')
                return jsonify(id=prior['id'],status=prior['status']),200
            if thread['assigned_to']!=g.user['id']:abort(409,description='Assuma esta conversa antes de responder.')
            mid=conn.execute("INSERT INTO inbox_messages(store_id,thread_id,direction,body,external_id,status,actor_id,created_at,payload_hash) VALUES(?,?,'out',?,?,'queued',?,?,?)",(g.store['id'],tid,body,'out:'+key,g.user['id'],h.now(),digest)).lastrowid
            conn.execute('UPDATE inbox_threads SET updated_at=? WHERE id=?',(h.now(),tid))
        return jsonify(id=mid,status='queued'),202

    @app.put('/api/admin/inbox/bot')
    @h.owner
    def inbox_bot_settings():
        enabled=h.boolean(h.data(),'enabled')
        if enabled and not g.store['inbox_hook_hash']:abort(409,description='Ative o recebimento de conversas primeiro.')
        h.db().execute('UPDATE stores SET inbox_bot=? WHERE id=?',(enabled,g.store['id']))
        return jsonify(ok=True)

    @app.post('/api/admin/inbox/<int:tid>/close')
    @h.owner
    def inbox_close(tid):
        with h.transaction() as conn:
            thread=h.owned('inbox_threads',tid)
            if thread['assigned_to'] not in (None,g.user['id']) and g.role not in ('owner','manager'):abort(403)
            conn.execute("UPDATE inbox_threads SET state='closed',assigned_to=NULL,unread=0 WHERE id=?",(tid,))
            conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE thread_id=? AND automated=1 AND status='queued'",(tid,))
        return jsonify(ok=True)

    @app.delete('/api/admin/inbox/<int:tid>')
    @h.owner
    def inbox_delete(tid):
        if g.role not in ('owner','manager'):abort(403)
        with h.transaction() as conn:
            h.owned('inbox_threads',tid)
            conn.execute('DELETE FROM inbox_messages WHERE thread_id=?',(tid,))
            conn.execute('DELETE FROM inbox_threads WHERE id=?',(tid,))
        return jsonify(ok=True)

    @app.cli.command('inbox-dispatch')
    @click.option('--limit',default=20,type=click.IntRange(1,100))
    def inbox_dispatch(limit):click.echo(json.dumps(dispatch_inbox(app,limit)))
