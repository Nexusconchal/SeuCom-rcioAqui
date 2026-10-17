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
from inbox_service import (preferences, sending_since, write_value, validate_preferences,
                           automatic_reply, template_values, render_message, delivery_health, normalize)

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


def dispatch_inbox(app,limit=20,stop_event=None):
    from database import connect
    provider=app.extensions.get('evolution') or Evolution(app.config.get('EVOLUTION_API_URL',''),app.config.get('EVOLUTION_API_KEY',''))
    if not provider.ready:return {'sent':0,'uncertain':0,'configured':False}
    result={'sent':0,'uncertain':0,'configured':True};conn=connect(app.config)
    try:
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        conn.execute("UPDATE inbox_messages SET status='uncertain' WHERE status='processing' AND claimed_at<?",((datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec='seconds'),))
        conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE status='queued' AND automated=1 AND created_at<?",((datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec='seconds'),))
        conn.execute("UPDATE inbox_messages SET status='held' WHERE status='queued' AND automated=0 AND COALESCE(claimed_at,created_at)<?",((datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(timespec='seconds'),))
        for _ in range(max(1,min(limit,100))):
            if stop_event is not None and stop_event.is_set():break
            conn.execute('BEGIN IMMEDIATE')
            try:
                row=conn.execute("""SELECT m.*,t.phone,s.wa_instance FROM inbox_messages m JOIN inbox_threads t ON t.id=m.thread_id
                    JOIN stores s ON s.id=m.store_id
                    JOIN platform_settings gate ON gate.key='inbox.sending.' || CAST(s.id AS TEXT)
                    WHERE m.status='queued' AND s.enabled=1 AND s.wa_instance!='' AND s.inbox_hook_hash!=''
                    AND gate.value!=''
                    AND (m.automated=0 OR (t.assigned_to IS NULL AND t.state='open' AND s.inbox_bot=1)) ORDER BY m.id LIMIT 1""").fetchone()
                if not row:conn.execute('COMMIT');break
                claimed=conn.execute("UPDATE inbox_messages SET status='processing',claimed_at=? WHERE id=? AND status='queued'",(now,row['id']))
                conn.execute('COMMIT')
                if claimed.rowcount!=1:continue
            except Exception:conn.execute('ROLLBACK');raise
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
        key=message.get('key') or {}
        if not isinstance(key,dict):abort(400)
        jid=key.get('remoteJid','')
        if not isinstance(jid,str):abort(400)
        if jid.endswith('@lid'):jid=key.get('remoteJidAlt','')
        if not isinstance(jid,str):abort(400)
        if key.get('fromMe') or not re.fullmatch(r'55\d{10,11}@s.whatsapp.net',jid):return jsonify(ignored=True)
        phone=jid.split('@')[0][2:];eid=key.get('id')
        if not isinstance(eid,str) or not 1<=len(eid)<=200:abort(400)
        content=message.get('message') or {}
        if not isinstance(content,dict):abort(400)
        for _ in range(2):
            wrapper=content.get('ephemeralMessage') or content.get('viewOnceMessage')
            if isinstance(wrapper,dict) and isinstance(wrapper.get('message'),dict):content=wrapper['message']
        extended=content.get('extendedTextMessage') or {}
        if not isinstance(extended,dict):abort(400)
        body=content.get('conversation') or extended.get('text') or '[Mensagem de mídia: confira no WhatsApp]'
        if not isinstance(body,str):abort(400)
        body=body[:4000];name=str(message.get('pushName') or phone)[:100];stamp=h.now()
        with h.transaction() as conn:
            if conn.execute('SELECT id FROM inbox_messages WHERE store_id=? AND external_id=?',(sid,'in:'+eid)).fetchone():return jsonify(ok=True,duplicate=True)
            conn.execute('''INSERT INTO inbox_threads(store_id,phone,name,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(store_id,phone) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at''',(sid,phone,name,stamp))
            thread=conn.execute('SELECT * FROM inbox_threads WHERE store_id=? AND phone=?',(sid,phone)).fetchone()
            conn.execute("UPDATE inbox_threads SET unread=unread+1,state=CASE WHEN state='closed' THEN 'open' ELSE state END WHERE id=?",(thread['id'],))
            conn.execute("INSERT INTO inbox_messages(store_id,thread_id,direction,body,external_id,status,created_at) VALUES(?,?,'in',?,?,'received',?)",(sid,thread['id'],body,'in:'+eid,stamp))
            normalized=normalize(body);reply=''
            human=bool(re.search(r'\b(atendente|humano)\b',normalized)) or body.startswith('[Mensagem de mídia:')
            if human:
                conn.execute("UPDATE inbox_threads SET state='human' WHERE id=?",(thread['id'],))
                conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE thread_id=? AND automated=1 AND status='queued'",(thread['id'],))
            elif s['inbox_bot'] and not thread['assigned_to'] and thread['state'] in ('open','closed'):
                base=app.config['PUBLIC_URL'] or request.host_url.rstrip('/')
                reply=automatic_reply(preferences(conn,sid),s,body,name,base)
                if not reply:conn.execute("UPDATE inbox_threads SET state='human' WHERE id=?",(thread['id'],))
                if thread['last_auto_at'] and thread['last_auto_at']>=(datetime.now(timezone.utc)-timedelta(seconds=3)).isoformat(timespec='seconds'):reply=''
                if reply:
                    conn.execute("INSERT INTO inbox_messages(store_id,thread_id,direction,body,external_id,status,automated,created_at) VALUES(?,?,'out',?,?,'queued',1,?)",(sid,thread['id'],reply,'auto:'+eid,stamp))
                    conn.execute('UPDATE inbox_threads SET last_auto_at=? WHERE id=?',(stamp,thread['id']))
        return jsonify(ok=True)

    @app.get('/api/admin/inbox')
    @h.owner
    def inbox_list():
        settings=preferences(h.db(),g.store['id'])
        return jsonify(configured=bool(g.store['inbox_hook_hash']),available=provider().ready and bool(g.store['wa_instance']),
            provider_available=provider().ready,linked=bool(g.store['wa_instance']),bot=bool(g.store['inbox_bot']),
            permissions={'connect':g.role=='owner','configure':g.role in ('owner','manager')},
            agents=h.rows('''SELECT id,name FROM users WHERE id=? OR id IN
                (SELECT user_id FROM store_members WHERE store_id=? AND active=1 AND role!='kitchen') ORDER BY name''',(g.store['owner_id'],g.store['id'])),
            sending=bool(sending_since(h.db(),g.store['id'])),delivery=delivery_health(app,h.db()),settings=settings,
            queue={r['status']:r['total'] for r in h.rows("SELECT status,COUNT(*) AS total FROM inbox_messages WHERE store_id=? AND direction='out' AND status IN ('queued','processing','held','uncertain') GROUP BY status",(g.store['id'],))},
            threads=h.rows('''SELECT t.*,u.name AS assigned_name,
                (SELECT body FROM inbox_messages m WHERE m.thread_id=t.id ORDER BY m.id DESC LIMIT 1) AS last_body,
                (SELECT direction FROM inbox_messages m WHERE m.thread_id=t.id ORDER BY m.id DESC LIMIT 1) AS last_direction
                FROM inbox_threads t LEFT JOIN users u ON u.id=t.assigned_to WHERE t.store_id=? ORDER BY t.updated_at DESC,t.id DESC LIMIT 200''',(g.store['id'],)))

    @app.get('/api/admin/inbox/connection')
    @h.owner
    def inbox_connection():
        if not provider().ready or not g.store['wa_instance']:
            return jsonify(connected=False,state='unlinked')
        code,value=provider().state(g.store['wa_instance'])
        instance=value.get('instance') if isinstance(value,dict) else None
        state=instance.get('state') if isinstance(instance,dict) else value.get('state') if isinstance(value,dict) else None
        return jsonify(connected=code==200 and state in ('open','connected'),state=state if state in ('open','connected','close','connecting') else 'unknown')

    @app.put('/api/admin/inbox/settings')
    @h.owner
    def inbox_settings():
        if g.role not in ('owner','manager'):abort(403)
        try:value=validate_preferences(h.data())
        except ValueError as exc:abort(400,description=str(exc))
        write_value(h.db(),'inbox.config.'+str(g.store['id']),json.dumps(value))
        return jsonify(ok=True,settings=value)

    @app.put('/api/admin/inbox/delivery')
    @h.owner
    def inbox_delivery():
        if g.role!='owner':abort(403)
        enabled=h.boolean(h.data(),'enabled')
        if enabled and (not provider().ready or not g.store['wa_instance'] or not g.store['inbox_hook_hash']):
            abort(409,description='Conecte o WhatsApp e ative o recebimento antes de autorizar envios.')
        if enabled:
            code,value=provider().state(g.store['wa_instance'])
            instance=value.get('instance') if isinstance(value,dict) else None
            state=instance.get('state') if isinstance(instance,dict) else value.get('state') if isinstance(value,dict) else None
            if code!=200 or state not in ('open','connected'):abort(409,description='A conexão do WhatsApp ainda não foi confirmada. Confira o QR Code e tente novamente.')
        with h.transaction() as conn:
            if enabled and sending_since(conn,g.store['id']):return jsonify(ok=True,sending=True)
            # Historical/unattempted replies are never silently released on activation.
            conn.execute("UPDATE inbox_messages SET status=CASE WHEN automated=1 THEN 'cancelled' ELSE 'held' END WHERE store_id=? AND status='queued'",(g.store['id'],))
            write_value(conn,'inbox.sending.'+str(g.store['id']),h.now() if enabled else '')
            if not enabled:conn.execute('UPDATE stores SET inbox_bot=0 WHERE id=?',(g.store['id'],))
        return jsonify(ok=True,sending=bool(enabled))

    @app.post('/api/admin/inbox/preview')
    @h.owner
    def inbox_preview():
        if g.role not in ('owner','manager'):abort(403)
        body=h.text(h.data(),'message',1,4000)
        base=app.config['PUBLIC_URL'] or request.host_url.rstrip('/')
        return jsonify(reply=automatic_reply(preferences(h.db(),g.store['id']),g.store,body,'Cliente',base),
                       human=bool(re.search(r'\b(atendente|humano)\b',normalize(body))))

    @app.get('/api/admin/inbox/<int:tid>')
    @h.owner
    def inbox_thread(tid):
        thread=h.owned('inbox_threads',tid)
        h.db().execute('UPDATE inbox_threads SET unread=0 WHERE id=?',(tid,))
        before=request.args.get('before','')
        if before and (not before.isdigit() or len(before)>16):abort(400)
        messages=h.rows('SELECT id,direction,body,status,automated,created_at FROM inbox_messages WHERE thread_id=?'+(' AND id<?' if before else '')+' ORDER BY id DESC LIMIT 101',(tid,int(before)) if before else (tid,))
        settings=preferences(h.db(),g.store['id']);base=app.config['PUBLIC_URL'] or request.host_url.rstrip('/')
        values=template_values(g.store,thread['name'],base)
        assigned=h.one('SELECT name FROM users WHERE id=?',(thread['assigned_to'],)) if thread['assigned_to'] else None
        return jsonify(thread={**dict(thread),'mine':thread['assigned_to']==g.user['id'],'assigned_name':assigned['name'] if assigned else None},messages=messages[:100],has_more=len(messages)>100,
                       quick_replies=[{**r,'rendered':render_message(r['message'],values)} for r in settings['quick_replies']])

    @app.post('/api/admin/inbox/messages/<int:mid>/action')
    @h.owner
    def inbox_message_action(mid):
        action=h.data().get('action')
        if action not in ('cancel','queue'):abort(400)
        with h.transaction() as conn:
            message=h.owned('inbox_messages',mid);thread=h.owned('inbox_threads',message['thread_id'])
            if thread['assigned_to']!=g.user['id']:abort(409,description='Assuma a conversa para revisar mensagens pendentes.')
            if action=='queue':
                if message['status']!='held' or message['automated'] or not sending_since(conn,g.store['id']):abort(409,description='Esta mensagem não pode ser colocada na fila.')
                conn.execute("UPDATE inbox_messages SET status='queued',claimed_at=? WHERE id=?",(h.now(),mid))
            else:
                changed=conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE id=? AND status IN ('queued','held')",(mid,))
                if changed.rowcount!=1:abort(409,description='A mensagem já está em processamento ou foi finalizada.')
        return jsonify(ok=True)

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

    @app.post('/api/admin/inbox/<int:tid>/assign')
    @h.owner
    def inbox_assign(tid):
        if g.role not in ('owner','manager'):abort(403)
        uid=h.integer(h.data(),'user_id',minimum=1)
        if uid!=g.store['owner_id'] and not h.one("SELECT id FROM store_members WHERE store_id=? AND user_id=? AND active=1 AND role!='kitchen'",(g.store['id'],uid)):
            abort(404,description='Atendente não encontrado nesta loja.')
        with h.transaction() as conn:
            h.owned('inbox_threads',tid)
            conn.execute("UPDATE inbox_threads SET assigned_to=?,state='human',updated_at=? WHERE id=?",(uid,h.now(),tid))
            conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE thread_id=? AND automated=1 AND status='queued'",(tid,))
        return jsonify(ok=True)

    @app.put('/api/admin/inbox/bot')
    @h.owner
    def inbox_bot_settings():
        enabled=h.boolean(h.data(),'enabled')
        if enabled and not g.store['inbox_hook_hash']:abort(409,description='Ative o recebimento de conversas primeiro.')
        with h.transaction() as conn:
            conn.execute('UPDATE stores SET inbox_bot=? WHERE id=?',(enabled,g.store['id']))
            if not enabled:conn.execute("UPDATE inbox_messages SET status='cancelled' WHERE store_id=? AND automated=1 AND status='queued'",(g.store['id'],))
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
