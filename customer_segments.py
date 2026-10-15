"""Públicos dinâmicos com condições explícitas, sem copiar dados entre lojas."""
import json
from types import SimpleNamespace

from flask import abort,g,jsonify

DDL="""
CREATE TABLE IF NOT EXISTS customer_segments (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, operator TEXT NOT NULL,
 rules TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_segments_store ON customer_segments(store_id);
"""
FIELDS={'orders','spent','ticket','days_since'}


def matches(customer,segment):
    results=[]
    for rule in json.loads(segment['rules']):
        x=customer[rule['field']];value=rule['value']
        results.append(x>=value if rule['comparison']=='gte' else x<=value if rule['comparison']=='lte' else x==value)
    return all(results) if segment['operator']=='and' else any(results)


def register_customer_segments(app,helpers):
    h=SimpleNamespace(**helpers)

    @app.get('/api/admin/marketing/segments')
    @h.owner
    def customer_segment_list():
        customers=app.extensions['marketing_customers'](g.store['id'])
        rows=h.rows('SELECT * FROM customer_segments WHERE store_id=? ORDER BY id DESC',(g.store['id'],))
        for segment in rows:
            segment['total']=sum(matches(c,segment) for c in customers)
            segment['authorized']=sum(c['consent'] and matches(c,segment) for c in customers)
            segment['members']=[c['phone'] for c in customers if matches(c,segment)]
            segment['rules']=json.loads(segment['rules'])
        return jsonify(segments=rows)

    @app.post('/api/admin/marketing/segments')
    @app.put('/api/admin/marketing/segments/<int:segid>')
    @h.owner
    def customer_segment_save(segid=None):
        value=h.data()
        if segid is not None:h.owned('customer_segments',segid)
        rules=value.get('rules');op=value.get('operator')
        if op not in ('and','or') or not isinstance(rules,list) or not 1<=len(rules)<=10:
            abort(400,description='Use até 10 condições e escolha todas (E) ou alguma (OU).')
        clean=[]
        for rule in rules:
            if not isinstance(rule,dict) or rule.get('field') not in FIELDS or rule.get('comparison') not in ('gte','lte','eq'):
                abort(400,description='Condição inválida.')
            clean.append({'field':rule['field'],'comparison':rule['comparison'],'value':h.integer(rule,'value',maximum=10**12)})
        fields=(h.text(value,'name',2,100),op,json.dumps(clean))
        if segid is None:
            segid=h.db().execute('INSERT INTO customer_segments(store_id,name,operator,rules,created_at) VALUES(?,?,?,?,?)',(g.store['id'],*fields,h.now())).lastrowid
        else:h.db().execute('UPDATE customer_segments SET name=?,operator=?,rules=? WHERE id=? AND store_id=?',(*fields,segid,g.store['id']))
        return jsonify(id=segid)
