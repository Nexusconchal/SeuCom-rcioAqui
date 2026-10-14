"""Regras de catálogo por canal, dia e horário, sempre aplicadas no servidor."""
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import abort, g, jsonify

TIMEZONES = ('America/Sao_Paulo', 'America/Manaus', 'America/Cuiaba', 'America/Rio_Branco',
             'America/Porto_Velho', 'America/Boa_Vista', 'America/Noronha', 'America/Belem',
             'America/Bahia', 'America/Fortaleza', 'America/Recife', 'America/Maceio', 'America/Araguaina', 'America/Campo_Grande')
DDL = """
CREATE TABLE IF NOT EXISTS catalog_rules (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), product_id INTEGER NOT NULL REFERENCES products(id),
 name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('price','visibility')), channels TEXT NOT NULL, days TEXT NOT NULL,
 start_time TEXT NOT NULL, end_time TEXT NOT NULL, value INTEGER NOT NULL, starts_on TEXT NOT NULL DEFAULT '',
 ends_on TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, priority INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_catalog_rules_store ON catalog_rules(store_id,product_id,active);
"""


def local_time(store, stamp=None):
    return (stamp or datetime.now(timezone.utc)).astimezone(ZoneInfo(dict(store).get('timezone', 'America/Sao_Paulo')))


def catalog_rule_map(conn,sid):
    rules={}
    for row in conn.execute('SELECT * FROM catalog_rules WHERE store_id=? AND active=1 ORDER BY priority DESC,id DESC',(sid,)):
        rules.setdefault(row['product_id'],[]).append(dict(row))
    return rules


def apply_rules(conn, store, product, channel, stamp=None, rules=None):
    result = dict(product)
    current = local_time(store, stamp)
    day, minute = current.weekday(), current.strftime('%H:%M')
    candidates = rules if rules is not None else conn.execute('SELECT * FROM catalog_rules WHERE store_id=? AND product_id=? AND active=1 ORDER BY priority DESC,id DESC', (store['id'], product['id'])).fetchall()
    applied = set()
    for rule in candidates:
        if channel not in json.loads(rule['channels']) or rule['kind'] in applied:
            continue
        # Madrugada pertence ao dia em que o intervalo começou.
        rule_day = (day - 1) % 7 if rule['start_time'] > rule['end_time'] and minute < rule['end_time'] else day
        date = current.date().isoformat()
        if rule['starts_on'] and date < rule['starts_on'] or rule['ends_on'] and date > rule['ends_on']:
            continue
        if rule_day not in json.loads(rule['days']):
            continue
        matches = (rule['start_time'] <= minute < rule['end_time'] if rule['start_time'] < rule['end_time'] else
                   minute >= rule['start_time'] or minute < rule['end_time'] if rule['start_time'] > rule['end_time'] else True)
        if not matches:
            continue
        applied.add(rule['kind'])
        if rule['kind'] == 'price':
            result['original_price'] = product['price']
            result['price'] = rule['value']
            result['promotion'] = rule['name']
        else:
            result['active'] = bool(rule['value']) and bool(product['active'])
    return result


def register_merchandising(app, helpers):
    h = SimpleNamespace(**helpers)

    @app.get('/api/admin/catalog-rules')
    @h.owner
    def catalog_rules_list():
        rules = h.rows('SELECT * FROM catalog_rules WHERE store_id=? ORDER BY priority DESC,id DESC', (g.store['id'],))
        for rule in rules:
            rule['channels'], rule['days'] = json.loads(rule['channels']), json.loads(rule['days'])
        return jsonify(rules=rules, timezones=TIMEZONES, timezone=g.store['timezone'], auto_accept=bool(g.store['auto_accept']))

    @app.post('/api/admin/catalog-rules')
    @app.put('/api/admin/catalog-rules/<int:rid>')
    @h.owner
    def catalog_rule_save(rid=None):
        value = h.data()
        if rid is not None:
            h.owned('catalog_rules', rid)
        pid = h.integer(value, 'product_id', minimum=1)
        h.owned('products', pid)
        channels, days = value.get('channels'), value.get('days')
        if not isinstance(channels, list) or not channels or any(c not in ('web', 'counter', 'dining') for c in channels) or len(set(channels)) != len(channels):
            abort(400, description='Escolha pelo menos um canal válido.')
        if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days) or len(set(days)) != len(days):
            abort(400, description='Escolha os dias da semana.')
        times = [h.text(value, key, 5, 5) for key in ('start_time', 'end_time')]
        if any(not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', t) for t in times):
            abort(400, description='Informe horários válidos.')
        dates = [h.text(value, key, 0, 10) for key in ('starts_on', 'ends_on')]
        try:
            for date in dates:
                if date:
                    datetime.strptime(date, '%Y-%m-%d')
            if all(dates) and dates[0] > dates[1]:
                raise ValueError()
        except ValueError:
            abort(400, description='Confira o período da regra.')
        kind = value.get('kind')
        if kind not in ('price', 'visibility'):
            abort(400, description='Tipo de regra inválido.')
        fields = (pid, h.text(value, 'name', 2, 100), kind, json.dumps(channels), json.dumps(days), *times,
                  h.integer(value, 'value', minimum=1 if kind == 'price' else 0, maximum=10**9 if kind == 'price' else 1), *dates,
                  h.boolean(value, 'active', True), h.integer(value, 'priority', maximum=100))
        if rid is None:
            rid = h.db().execute('INSERT INTO catalog_rules(store_id,product_id,name,kind,channels,days,start_time,end_time,value,starts_on,ends_on,active,priority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (g.store['id'], *fields)).lastrowid
        else:
            h.db().execute('UPDATE catalog_rules SET product_id=?,name=?,kind=?,channels=?,days=?,start_time=?,end_time=?,value=?,starts_on=?,ends_on=?,active=?,priority=? WHERE id=? AND store_id=?', (*fields, rid, g.store['id']))
        return jsonify(id=rid)

    @app.delete('/api/admin/catalog-rules/<int:rid>')
    @h.owner
    def catalog_rule_delete(rid):
        h.owned('catalog_rules', rid)
        h.db().execute('DELETE FROM catalog_rules WHERE id=? AND store_id=?', (rid, g.store['id']))
        return jsonify(ok=True)

    @app.put('/api/admin/operation-settings')
    @h.owner
    def operation_settings():
        value = h.data()
        zone = value.get('timezone', g.store['timezone'])
        if zone not in TIMEZONES:
            abort(400, description='Escolha um fuso horário brasileiro.')
        h.db().execute('UPDATE stores SET timezone=?,auto_accept=? WHERE id=?', (zone, h.boolean(value, 'auto_accept', bool(g.store['auto_accept'])), g.store['id']))
        return jsonify(ok=True)
