"""Uma entrada pública para várias lojas, mediante aceite de cada proprietário."""
import hashlib
import re
import secrets
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

from flask import abort,g,jsonify,request

DDL="""
CREATE TABLE IF NOT EXISTS store_networks (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL UNIQUE REFERENCES users(id), name TEXT NOT NULL,
 slug TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS network_stores (
 id INTEGER PRIMARY KEY, network_id INTEGER NOT NULL REFERENCES store_networks(id), store_id INTEGER NOT NULL REFERENCES stores(id),
 accepted_at TEXT NOT NULL, UNIQUE(network_id,store_id)
);
CREATE TABLE IF NOT EXISTS network_invites (
 id INTEGER PRIMARY KEY, network_id INTEGER NOT NULL REFERENCES store_networks(id), store_id INTEGER NOT NULL REFERENCES stores(id),
 token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, accepted_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_network_store ON network_stores(store_id);
"""


def register_store_network(app,helpers):
    h=SimpleNamespace(**helpers)
    def owner_only():
        if g.role!='owner':abort(403,description='Somente o dono pode vincular a loja a uma rede.')
    def network():
        owner_only();row=h.one('SELECT * FROM store_networks WHERE owner_id=?',(g.user['id'],))
        if not row:abort(404,description='Cadastre a rede primeiro.')
        return row

    @app.get('/api/network/<slug>')
    def network_public(slug):
        row=h.one('SELECT id,name,slug,description FROM store_networks WHERE slug=?',(slug,))
        if not row:abort(404,description='Rede não encontrada.')
        stores=h.rows('''SELECT s.id,s.name,s.slug,s.description,s.address,s.logo,s.banner,s.open,s.enabled,s.hours,s.auto_hours,
            s.timezone,s.billing_exempt,s.sub_status,s.paid_until,s.trial_until FROM network_stores n JOIN stores s ON s.id=n.store_id
            WHERE n.network_id=? AND s.enabled=1 ORDER BY s.name''',(row['id'],))
        from app import store_status
        for s in stores:
            open_now,label=store_status(s)
            for k in ('hours','auto_hours','timezone','billing_exempt','sub_status','paid_until','trial_until','enabled','open'):s.pop(k,None)
            s['open_now'],s['status_text']=open_now,label
        return jsonify(network=dict(row),stores=stores)

    @app.get('/api/admin/network')
    @h.owner
    def network_settings():
        owner_only();row=h.one('SELECT * FROM store_networks WHERE owner_id=?',(g.user['id'],))
        members=h.rows('SELECT s.id,s.name,s.slug,s.address FROM network_stores n JOIN stores s ON s.id=n.store_id WHERE n.network_id=? ORDER BY s.name',(row['id'],)) if row else []
        joined=h.rows('SELECT n.id,n.name,n.slug FROM network_stores m JOIN store_networks n ON n.id=m.network_id WHERE m.store_id=?',(g.store['id'],))
        return jsonify(network=dict(row) if row else None,stores=members,joined=joined)

    @app.post('/api/admin/network')
    @h.owner
    def network_save():
        owner_only();value=h.data();slug=h.text(value,'slug',3,60)
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug):abort(400,description='Use letras minúsculas, números e hífens no link da rede.')
        with h.transaction() as conn:
            current=conn.execute('SELECT * FROM store_networks WHERE owner_id=?',(g.user['id'],)).fetchone()
            fields=(h.text(value,'name',2,100),slug,h.text(value,'description',0,500))
            if current:
                nid=current['id'];conn.execute('UPDATE store_networks SET name=?,slug=?,description=? WHERE id=?',(*fields,nid))
            else:nid=conn.execute('INSERT INTO store_networks(owner_id,name,slug,description) VALUES(?,?,?,?)',(g.user['id'],*fields)).lastrowid
            conn.execute('INSERT INTO network_stores(network_id,store_id,accepted_at) VALUES(?,?,?) ON CONFLICT(network_id,store_id) DO NOTHING',(nid,g.store['id'],h.now()))
        return jsonify(id=nid)

    @app.post('/api/admin/network/invite')
    @h.owner
    def network_invite():
        row=network();value=h.data();slug=h.text(value,'store_slug',3,60)
        store=h.one('SELECT id FROM stores WHERE slug=?',(slug,))
        if not store:abort(404,description='Loja não encontrada. Informe o final do link do cardápio.')
        token=secrets.token_urlsafe(32)
        with h.transaction() as conn:
            conn.execute('DELETE FROM network_invites WHERE network_id=? AND store_id=? AND accepted_at IS NULL',(row['id'],store['id']))
            conn.execute('INSERT INTO network_invites(network_id,store_id,token_hash,expires_at) VALUES(?,?,?,?)',(row['id'],store['id'],hashlib.sha256(token.encode()).hexdigest(),(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(timespec='seconds')))
        base=app.config['PUBLIC_URL'] or request.host_url.rstrip('/')
        return jsonify(url=base+'/painel?rede_convite='+token)

    @app.post('/api/admin/network/accept')
    @h.owner
    def network_accept():
        owner_only();token=h.text(h.data(),'token',40,80)
        with h.transaction() as conn:
            invitation=conn.execute('SELECT * FROM network_invites WHERE token_hash=? AND store_id=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),g.store['id'],h.now())).fetchone()
            if not invitation:abort(404,description='Convite inválido, expirado ou dirigido a outra loja.')
            if invitation['accepted_at']:
                if conn.execute('SELECT id FROM network_stores WHERE network_id=? AND store_id=?',(invitation['network_id'],g.store['id'])).fetchone():
                    return jsonify(ok=True,already_accepted=True)
                abort(409,description='Este convite já foi utilizado. Solicite um novo convite à rede.')
            conn.execute('INSERT INTO network_stores(network_id,store_id,accepted_at) VALUES(?,?,?) ON CONFLICT(network_id,store_id) DO NOTHING',(invitation['network_id'],g.store['id'],h.now()))
            conn.execute('UPDATE network_invites SET accepted_at=? WHERE id=?',(h.now(),invitation['id']))
        return jsonify(ok=True)

    @app.post('/api/admin/network/preview-invite')
    @h.owner
    def network_preview_invite():
        owner_only();token=h.text(h.data(),'token',40,80)
        row=h.one('SELECT n.name,n.slug,s.name AS store_name FROM network_invites i JOIN store_networks n ON n.id=i.network_id JOIN stores s ON s.id=i.store_id WHERE i.token_hash=? AND i.store_id=? AND i.expires_at>?',
                  (hashlib.sha256(token.encode()).hexdigest(),g.store['id'],h.now()))
        if not row:abort(404,description='Convite inválido, expirado ou dirigido a outra loja.')
        return jsonify(invite=dict(row))

    @app.delete('/api/admin/network/stores/<int:sid>')
    @h.owner
    def network_remove(sid):
        row=network()
        h.db().execute('DELETE FROM network_stores WHERE network_id=? AND store_id=?',(row['id'],sid))
        return jsonify(ok=True)

    @app.post('/api/admin/network/<int:nid>/leave')
    @h.owner
    def network_leave(nid):
        owner_only();h.db().execute('DELETE FROM network_stores WHERE network_id=? AND store_id=?',(nid,g.store['id']))
        return jsonify(ok=True)
