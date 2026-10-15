"""Áreas de entrega por faixa de CEP e limites por pedido."""
import json
import hashlib
import re
from types import SimpleNamespace

from flask import abort,g,jsonify


def postal_fee(store,value,subtotal):
    zones=json.loads(store['postal_zones'])
    if not zones:return None
    cep=value.get('cep','')
    if not isinstance(cep,str) or not re.fullmatch(r'\d{5}-?\d{3}',cep):
        abort(400,description='Informe o CEP para conferir a área e o valor da entrega.')
    number=int(cep.replace('-',''))
    matches=[z for z in zones if z['min_cep']<=number<=z['max_cep']]
    if not matches:abort(409,description='Este CEP está fora das áreas de entrega da loja.')
    zone=sorted(matches,key=lambda z:(-z['priority'],z['max_cep']-z['min_cep']))[0]
    if not zone['enabled']:abort(409,description='A entrega está indisponível para este CEP.')
    if subtotal<zone['minimum']:
        abort(400,description=f"Pedido mínimo nesta área: R$ {zone['minimum']/100:.2f} em produtos após descontos.")
    return (0 if zone['free_above'] is not None and subtotal>=zone['free_above'] else zone['fee']),zone['name']


def register_shipping(app,helpers):
    h=SimpleNamespace(**helpers)

    @app.get('/api/admin/shipping')
    @h.owner
    def shipping_settings():return jsonify(zones=json.loads(g.store['postal_zones']),version=hashlib.sha256(g.store['postal_zones'].encode()).hexdigest(),can_edit=g.role in ('owner','manager'))

    @app.put('/api/admin/shipping')
    @h.owner
    def shipping_save():
        value=h.data();zones=value.get('zones')
        if not isinstance(zones,list) or len(zones)>100:abort(400,description='Use até 100 faixas de CEP.')
        clean=[]
        for z in zones:
            if not isinstance(z,dict):abort(400,description='Área de entrega inválida.')
            low,high=h.integer(z,'min_cep',maximum=99999999),h.integer(z,'max_cep',maximum=99999999)
            if low>high:abort(400,description='O CEP inicial não pode passar do CEP final.')
            clean.append({'name':h.text(z,'name',2,80),'min_cep':low,'max_cep':high,'fee':h.integer(z,'fee',maximum=100000),
                'minimum':h.integer(z,'minimum',default=0,maximum=10**9),'free_above':None if z.get('free_above') is None else h.integer(z,'free_above',maximum=10**9),
                'enabled':h.boolean(z,'enabled',True),'priority':h.integer(z,'priority',default=0,maximum=100)})
        with h.transaction() as conn:
            previous=conn.execute('SELECT postal_zones FROM stores WHERE id=?',(g.store['id'],)).fetchone()[0]
            if value.get('expected_version') and value['expected_version']!=hashlib.sha256(previous.encode()).hexdigest():
                abort(409,description='As áreas de entrega mudaram. Atualize a página antes de salvar.')
            conn.execute('UPDATE stores SET postal_zones=? WHERE id=?',(json.dumps(clean),g.store['id']))
        return jsonify(ok=True)
