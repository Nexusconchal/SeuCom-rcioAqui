"""Posições recentes de entregadores; links individuais podem ser revogados."""
import hashlib
import math
import re
import secrets
from types import SimpleNamespace

from flask import abort,g,jsonify,request


def coordinate(value,key,low,high,optional=False):
    v=value.get(key)
    if optional and v is None:return None
    if type(v) not in (int,float) or not math.isfinite(v) or not low<=v<=high:
        abort(400,description='Posição inválida. Informe uma coordenada válida no Brasil.')
    return round(v,6)


def register_delivery_map(app,helpers):
    h=SimpleNamespace(**helpers)

    @app.get('/api/admin/delivery-map')
    @h.owner
    def delivery_map():
        return jsonify(drivers=h.rows('SELECT id,name,phone,active,gps_lat,gps_lon,gps_accuracy,gps_at FROM drivers WHERE store_id=? ORDER BY active DESC,name',(g.store['id'],)),
            orders=h.rows("SELECT id,number,customer,address,total,paid,driver_id,status,latitude,longitude FROM orders WHERE store_id=? AND mode='delivery' AND status NOT IN ('completed','cancelled') ORDER BY id",(g.store['id'],)))

    @app.post('/api/admin/drivers/<int:did>/location-link')
    @h.owner
    def driver_location_link(did):
        value=h.data();h.owned('drivers',did)
        revoke=h.boolean(value,'revoke');token='' if revoke else secrets.token_urlsafe(32)
        h.db().execute('UPDATE drivers SET gps_hash=?,gps_lat=NULL,gps_lon=NULL,gps_at=NULL WHERE id=? AND store_id=?',('' if revoke else hashlib.sha256(token.encode()).hexdigest(),did,g.store['id']))
        base=app.config['PUBLIC_URL'] or request.host_url.rstrip('/')
        return jsonify(url='' if revoke else base+'/entregador/#'+str(did)+':'+token)

    def driver():
        token=request.headers.get('Authorization','').removeprefix('Bearer ')
        if not re.fullmatch(r'[A-Za-z0-9_-]{40,80}',token):abort(401,description='Link do entregador inválido ou revogado.')
        row=h.one('SELECT d.*,s.name AS store_name,s.enabled FROM drivers d JOIN stores s ON s.id=d.store_id WHERE d.gps_hash=? AND d.active=1',(hashlib.sha256(token.encode()).hexdigest(),))
        if not row or not row['enabled']:abort(401,description='Link do entregador inválido ou revogado.')
        return row

    @app.get('/api/driver/route')
    def driver_route():
        d=driver()
        from operations import receipt_state
        orders=h.rows("SELECT id,number,customer,phone,address,latitude,longitude,total,paid,payment,change_for FROM orders WHERE store_id=? AND driver_id=? AND status='delivering' ORDER BY route_position,updated_at,id",(d['store_id'],d['id']))
        balances,_=receipt_state(h.db(),d['store_id'],orders)
        for o in orders:o['remaining_amount']=max(0,o['total']-balances[o['id']]);o.pop('id',None)
        return jsonify(driver=d['name'],store=d['store_name'],orders=orders)

    @app.post('/api/driver/location')
    def driver_location():
        d=driver();h.limited('driver-position:'+str(d['id']),180,3600,per_ip=False);value=h.data()
        if h.boolean(value,'stopped'):
            with h.transaction() as conn:
                d=driver()
                conn.execute('UPDATE drivers SET gps_lat=NULL,gps_lon=NULL,gps_at=NULL WHERE id=?',(d['id'],))
            return jsonify(ok=True)
        lat=coordinate(value,'latitude',-34,6);lon=coordinate(value,'longitude',-74,-28)
        accuracy=coordinate(value,'accuracy',0,10000)
        with h.transaction() as conn:
            d=driver()
            conn.execute('UPDATE drivers SET gps_lat=?,gps_lon=?,gps_accuracy=?,gps_at=? WHERE id=?',(lat,lon,accuracy,h.now(),d['id']))
        return jsonify(ok=True)

    @app.post('/api/admin/delivery-map/dispatch')
    @h.owner
    def route_dispatch():
        value=h.data();ids=value.get('order_ids');did=h.integer(value,'driver_id',minimum=1)
        if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(type(x) is not int for x in ids) or len(set(ids))!=len(ids):
            abort(400,description='Escolha de 1 a 10 pedidos prontos para a saída.')
        with h.transaction() as conn:
            d=h.owned('drivers',did)
            if not d['active']:abort(409,description='Este entregador está inativo.')
            for oid in ids:
                o=h.owned('orders',oid)
                if o['status']!='ready' or o['mode']!='delivery':abort(409,description='Todos os pedidos precisam estar prontos e ser de entrega.')
            position=conn.execute("SELECT COALESCE(MAX(route_position),0) FROM orders WHERE store_id=? AND driver_id=? AND status='delivering'",(g.store['id'],did)).fetchone()[0]
            for index,oid in enumerate(ids,1):
                conn.execute("UPDATE orders SET driver_id=?,status='delivering',updated_at=?,route_position=? WHERE id=?",(did,h.now(),position+index,oid))
                conn.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,'delivering',?)",(oid,h.now()))
        for oid in ids:app.extensions['on_status'](g.store['id'],oid,'delivering')
        return jsonify(dispatched=len(ids))

    def save_destination(conn,oid,value):
        lat=coordinate(value,'latitude',-34,6,True);lon=coordinate(value,'longitude',-74,-28,True)
        if (lat is None)!=(lon is None):abort(400,description='Informe latitude e longitude juntas.')
        if lat is not None:
            if value.get('mode')!='delivery':abort(400,description='A posição de destino é usada somente na entrega.')
            conn.execute('UPDATE orders SET latitude=?,longitude=? WHERE id=?',(lat,lon,oid))

    app.extensions['save_destination']=save_destination
