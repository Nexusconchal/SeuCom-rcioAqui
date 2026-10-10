"""Private management, platform accounting and tenant-scoped partner API."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import click
from flask import abort, g, jsonify, request, session

ZONE = ZoneInfo('America/Sao_Paulo')
SCOPES = {'orders:read', 'deliveries:write'}


def start_of_period(days):
    return (datetime.now(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
            - timedelta(days=days-1)).astimezone(timezone.utc).isoformat(timespec='seconds')


def month_bounds(label):
    """Início e fim (UTC, ISO) do mês AAAA-MM no fuso de São Paulo."""
    if not isinstance(label, str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', label):
        abort(400, description='Mês inválido.')
    year, month = int(label[:4]), int(label[5:])
    start = datetime(year, month, 1, tzinfo=ZONE)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=ZONE)
    return (start.astimezone(timezone.utc).isoformat(timespec='seconds'),
            end.astimezone(timezone.utc).isoformat(timespec='seconds'))


def effective_fee(store, today):
    """Mensalidade vigente: a promocional enquanto estiver no prazo."""
    if store['promo_fee'] is not None and store['promo_until'] and store['promo_until'] >= today:
        return store['promo_fee']
    return store['monthly_fee']


def finance(conn, sid, start):
    orders = [dict(r) for r in conn.execute('''SELECT o.*,SUM(i.quantity*i.unit_cost) AS cogs,SUM(CASE WHEN i.unit_cost IS NULL THEN 1 ELSE 0 END) AS missing
        FROM orders o LEFT JOIN order_items i ON i.order_id=o.id
        WHERE o.store_id=? AND o.created_at>=? AND o.status='completed' GROUP BY o.id ''', (sid, start))]
    revenue = sum(o['total'] for o in orders)
    missing = sum(bool(o['missing'] or o['cogs'] is None or o['delivery_cost'] is None
                       or o['payment_fee'] is None or o['platform_fee'] is None) for o in orders)
    cogs = sum(o['cogs'] or 0 for o in orders)
    delivery = sum(o['delivery_cost'] or 0 for o in orders)
    payment = sum(o['payment_fee'] or 0 for o in orders)
    commission = sum(o['platform_fee'] or 0 for o in orders)
    expenses = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE store_id=? AND created_at>=? AND category!='inventory'", (sid,start)).fetchone()[0]
    profit = None if missing else revenue-cogs-delivery-payment-commission-expenses
    return dict(revenue=revenue, cogs=cogs, delivery_cost=delivery, payment_fees=payment, platform_fees=commission,
                expenses=expenses, estimated_profit=profit, missing_cost_orders=missing, completed=len(orders),
                margin=None if profit is None or not revenue else round(profit/revenue*100, 1),
                cost_coverage=100 if not orders else round((len(orders)-missing)/len(orders)*100))


def register_business(app, helpers):
    h = SimpleNamespace(**helpers)

    def audit(action, detail='', sid=None):
        h.db().execute('INSERT INTO audit_log(actor_id,store_id,action,detail,created_at) VALUES(?,?,?,?,?)',
                       (g.user['id'] if getattr(g,'user',None) else None, sid, action, detail, h.now()))

    def platform(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = h.one('SELECT id,name,email,auth_version,platform_admin FROM users WHERE id=?', (session.get('uid',-1),))
            if not user or user['auth_version'] != session.get('version'):
                abort(401, description='Entre na sua conta.')
            if not user['platform_admin']:
                abort(403, description='Esta área é exclusiva do dono da plataforma.')
            g.user = user
            return fn(*args, **kwargs)
        return wrapped

    def days():
        value = request.args.get('days', '30')
        if value not in ('1','7','30','90','365'):
            abort(400, description='Período inválido.')
        return int(value)

    @app.get('/api/admin/finance')
    @h.owner
    def merchant_finance():
        start = start_of_period(days())
        result = finance(h.db(),g.store['id'],start)
        result['orders'] = h.rows('''SELECT o.id,o.number,o.customer,o.status,o.total,o.delivery_cost,o.payment_fee,o.platform_fee,
            SUM(CASE WHEN i.unit_cost IS NULL THEN 1 ELSE 0 END) AS missing_items,SUM(i.quantity*i.unit_cost) AS cogs
             FROM orders o LEFT JOIN order_items i ON i.order_id=o.id
             WHERE o.store_id=? AND o.created_at>=? AND o.status!='cancelled' GROUP BY o.id ORDER BY o.id DESC LIMIT 500''',(g.store['id'],start))
        result['fees'] = json.loads(g.store['payment_fees'])
        result['default_delivery_cost'] = g.store['default_delivery_cost']
        result['commission_bps'] = g.store['commission_bps']
        result['monthly_fee'] = g.store['monthly_fee']
        return jsonify(result)

    @app.put('/api/admin/finance/settings')
    @h.owner
    def finance_settings():
        value = h.data()
        fees = value.get('payment_fees', {})
        if not isinstance(fees,dict) or any(k not in ('pix','cash','card') for k in fees):
            abort(400, description='Taxas inválidas.')
        sanitized = {m:h.integer(fees,m,maximum=10000) for m in ('pix','cash','card')}
        delivery = value.get('default_delivery_cost')
        if delivery is not None:
            delivery = h.integer(value,'default_delivery_cost')
        h.db().execute('UPDATE stores SET payment_fees=?,default_delivery_cost=? WHERE id=?',
                       (json.dumps(sanitized),delivery,g.store['id']))
        return jsonify(ok=True)

    @app.patch('/api/admin/orders/<int:oid>/costs')
    @h.owner
    def order_costs(oid):
        value=h.data()
        with h.transaction() as conn:
            order=h.owned('orders',oid)
            delivery=value.get('delivery_cost',order['delivery_cost'])
            if delivery is not None:
                delivery=h.integer({'delivery_cost':delivery},'delivery_cost')
            if order['mode']=='pickup' and delivery not in (0,None):
                abort(400,description='Retirada não tem custo de entrega.')
            fee=value.get('payment_fee',order['payment_fee'])
            if fee is not None:
                fee=h.integer({'payment_fee':fee},'payment_fee')
            items=value.get('items',[])
            if not isinstance(items,list) or len(items)>50:
                abort(400,description='Custos inválidos.')
            for item in items:
                if not isinstance(item,dict):
                    abort(400,description='Custo inválido.')
                iid=h.integer(item,'id',minimum=1)
                if not h.one('SELECT id FROM order_items WHERE id=? AND order_id=?',(iid,oid)):
                    abort(404,description='Item não encontrado.')
                cost=None if item.get('unit_cost') is None else h.integer(item,'unit_cost')
                conn.execute('UPDATE order_items SET unit_cost=? WHERE id=? AND order_id=?',(cost,iid,oid))
            conn.execute('UPDATE orders SET delivery_cost=?,payment_fee=? WHERE id=?',(0 if order['mode']=='pickup' else delivery,fee,oid))
            audit('order.costs',str(oid),g.store['id'])
        return jsonify(ok=True)

    @app.get('/api/admin/customers')
    @h.owner
    def customers():
        # Normalize legacy formatted phone numbers without modifying customer records.
        phone="REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone,' ',''),'-',''),'(',''),')',''),'+','')"
        result=h.rows(f'''SELECT {phone} AS phone,MAX(customer) AS name,COUNT(*) AS orders,
            SUM(CASE WHEN status='completed' THEN total ELSE 0 END) AS spent,MAX(created_at) AS last_order
            FROM orders WHERE store_id=? AND status!='cancelled' GROUP BY {phone} ORDER BY spent DESC LIMIT 1000''',(g.store['id'],))
        return jsonify(customers=result)

    @app.get('/api/admin/customers/<phone>/orders')
    @h.owner
    def customer_orders(phone):
        if not re.fullmatch(r'\d{10,13}',phone):
            abort(400,description='Telefone inválido.')
        normalized="REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone,' ',''),'-',''),'(',''),')',''),'+','')"
        return jsonify(orders=[h.order_dict(o) for o in h.db().execute(f'SELECT * FROM orders WHERE store_id=? AND {normalized}=? ORDER BY id DESC LIMIT 100',(g.store['id'],phone))])

    @app.get('/api/admin/stock')
    @h.owner
    def stock():
        return jsonify(products=h.rows('SELECT id,name,stock,low_stock,unit_cost,active FROM products WHERE store_id=? ORDER BY name',(g.store['id'],)),
                       movements=h.rows('''SELECT m.*,p.name FROM stock_movements m JOIN products p ON p.id=m.product_id
                         WHERE m.store_id=? ORDER BY m.id DESC LIMIT 100''',(g.store['id'],)))

    @app.post('/api/admin/stock/<int:pid>/adjust')
    @h.owner
    def adjust_stock(pid):
        value=h.data()
        delta=h.integer(value,'delta',minimum=-1000000,maximum=1000000)
        reason=h.text(value,'reason',3,200)
        with h.transaction() as conn:
            product=h.owned('products',pid)
            if product['stock'] is None:
                abort(409,description='Ative o controle de estoque no produto primeiro.')
            balance=product['stock']+delta
            if not delta or balance<0 or balance>1000000:
                abort(400,description='Movimentação inválida ou saldo insuficiente.')
            conn.execute('UPDATE products SET stock=? WHERE id=?',(balance,pid))
            conn.execute('INSERT INTO stock_movements(store_id,product_id,delta,balance,reason,created_at) VALUES(?,?,?,?,?,?)',
                         (g.store['id'],pid,delta,balance,reason,h.now()))
        return jsonify(stock=balance)

    @app.get('/api/admin/insights')
    @h.owner
    def insights():
        start=start_of_period(days())
        return jsonify(finance=finance(h.db(),g.store['id'],start),
            top_products=h.rows('''SELECT i.name,SUM(i.quantity) AS quantity,SUM(i.quantity*i.unit_price) AS total
             FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.store_id=? AND o.status='completed' AND o.created_at>=?
             GROUP BY i.name ORDER BY total DESC LIMIT 5''',(g.store['id'],start)),
            low_stock=h.rows('SELECT id,name,stock FROM products WHERE store_id=? AND active=1 AND stock<=low_stock ORDER BY stock LIMIT 10',(g.store['id'],)),
            readiness={'products':h.one('SELECT COUNT(*) FROM products WHERE store_id=? AND active=1',(g.store['id'],))[0],
                       'photos':h.one("SELECT COUNT(*) FROM products WHERE store_id=? AND active=1 AND image!=''",(g.store['id'],))[0],
                       'costs':h.one('SELECT COUNT(*) FROM products WHERE store_id=? AND active=1 AND unit_cost IS NOT NULL',(g.store['id'],))[0],
                       'address':bool(g.store['address']), 'phone':bool(g.store['phone']), 'open':bool(g.store['open'])})

    @app.get('/api/platform/summary')
    @platform
    def platform_summary():
        start=start_of_period(days())
        month=month_bounds(datetime.now(ZONE).strftime('%Y-%m'))
        today=datetime.now(ZONE).date().isoformat()
        stores=h.rows('''SELECT s.id,s.name,s.slug,s.open,s.enabled,s.blocked_reason,s.commission_bps,s.monthly_fee,
             s.promo_fee,s.promo_until,s.promo_label,s.created_at,s.phone,s.pix_key,s.address,u.email,
             COALESCE(o.orders,0) AS orders,COALESCE(o.revenue,0) AS revenue,COALESCE(o.commission,0) AS commission,
             COALESCE(o.missing,0) AS missing_fees,COALESCE(l.received,0) AS received,COALESCE(l.expenses,0) AS expenses,
             COALESCE(m.received,0) AS received_month,a.last_order,COALESCE(p.products,0) AS products
             FROM stores s JOIN users u ON u.id=s.owner_id LEFT JOIN
             (SELECT store_id,COUNT(*) AS orders,SUM(total) AS revenue,SUM(platform_fee) AS commission,
              SUM(CASE WHEN platform_fee IS NULL THEN 1 ELSE 0 END) AS missing FROM orders WHERE status='completed'
              AND created_at>=? GROUP BY store_id) o ON o.store_id=s.id LEFT JOIN
             (SELECT store_id,SUM(CASE WHEN kind='receipt' THEN amount ELSE 0 END) AS received,
              SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END) AS expenses FROM platform_ledger WHERE created_at>=? AND voided_at IS NULL
              GROUP BY store_id) l ON l.store_id=s.id LEFT JOIN
             (SELECT store_id,SUM(amount) AS received FROM platform_ledger WHERE kind='receipt' AND voided_at IS NULL
              AND created_at>=? AND created_at<? GROUP BY store_id) m ON m.store_id=s.id LEFT JOIN
             (SELECT store_id,MAX(created_at) AS last_order FROM orders GROUP BY store_id) a ON a.store_id=s.id LEFT JOIN
             (SELECT store_id,COUNT(*) AS products FROM products WHERE active=1 GROUP BY store_id) p ON p.store_id=s.id
             ORDER BY s.id DESC LIMIT 1000''',(start,start,*month))
        for s in stores:
            s['effective_fee']=effective_fee(s,today)
            s['promo_active']=s['effective_fee']!=s['monthly_fee']
            s['overdue']=bool(s['enabled'] and s['effective_fee'] and s['received_month']<s['effective_fee'])
            s['setup']={'products':s['products']>0,'phone':bool(s.pop('phone')),'pix':bool(s.pop('pix_key')),'address':bool(s.pop('address'))}
        ledger=h.rows('SELECT l.*,s.name AS store_name FROM platform_ledger l LEFT JOIN stores s ON s.id=l.store_id WHERE l.created_at>=? ORDER BY l.id DESC LIMIT 200',(start,))
        totals=h.one("SELECT COALESCE(SUM(CASE WHEN kind='receipt' THEN amount ELSE 0 END),0) AS received,COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END),0) AS expenses FROM platform_ledger WHERE created_at>=? AND voided_at IS NULL",(start,))
        return jsonify(stores=stores,ledger=ledger,received=totals['received'],expenses=totals['expenses'],
                       cash_result=totals['received']-totals['expenses'],commission=sum(s['commission'] for s in stores),
                       monthly_recurring=sum(s['effective_fee'] for s in stores if s['enabled']),
                       overdue=sum(max(0,s['effective_fee']-s['received_month']) for s in stores if s['overdue']),
                       gross_store_sales=sum(s['revenue'] for s in stores),
                       audit=h.rows('SELECT action,detail,created_at FROM audit_log ORDER BY id DESC LIMIT 30'))

    @app.get('/api/platform/monthly')
    @platform
    def platform_monthly():
        """Evolução mês a mês e ranking das lojas no mês escolhido."""
        try:
            count=int(request.args.get('months','12'))
        except ValueError:
            abort(400,description='Quantidade de meses inválida.')
        if not 1<=count<=36:
            abort(400,description='Use de 1 a 36 meses.')
        current=datetime.now(ZONE).replace(day=1)
        labels=[]
        year,mon=current.year,current.month
        for _ in range(count):
            labels.append(f'{year:04d}-{mon:02d}')
            year,mon=(year,mon-1) if mon>1 else (year-1,12)
        months=[]
        for label in reversed(labels):
            start,end=month_bounds(label)
            o=h.one('''SELECT COUNT(*) AS orders,COALESCE(SUM(total),0) AS gmv,COALESCE(SUM(platform_fee),0) AS commission,
                COUNT(DISTINCT store_id) AS active_stores FROM orders WHERE status='completed' AND created_at>=? AND created_at<?''',(start,end))
            c=h.one("SELECT COUNT(*) FROM orders WHERE status='cancelled' AND created_at>=? AND created_at<?",(start,end))[0]
            l=h.one('''SELECT COALESCE(SUM(CASE WHEN kind='receipt' THEN amount ELSE 0 END),0) AS received,
                COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END),0) AS expenses
                FROM platform_ledger WHERE voided_at IS NULL AND created_at>=? AND created_at<?''',(start,end))
            n=h.one('SELECT COUNT(*) FROM stores WHERE created_at>=? AND created_at<?',(start,end))[0]
            months.append(dict(month=label,orders=o['orders'],gmv=o['gmv'],commission=o['commission'],active_stores=o['active_stores'],
                               cancelled=c,received=l['received'],expenses=l['expenses'],result=l['received']-l['expenses'],new_stores=n,
                               ticket=o['gmv']//o['orders'] if o['orders'] else 0))
        selected=request.args.get('month',labels[0])
        start,end=month_bounds(selected)
        ranking=h.rows('''SELECT s.id,s.name,s.enabled,COUNT(o.id) AS orders,COALESCE(SUM(o.total),0) AS gmv,
            COALESCE(SUM(o.platform_fee),0) AS commission,COALESCE(MAX(r.received),0) AS received
            FROM stores s LEFT JOIN orders o ON o.store_id=s.id AND o.status='completed' AND o.created_at>=? AND o.created_at<?
            LEFT JOIN (SELECT store_id,SUM(amount) AS received FROM platform_ledger WHERE kind='receipt' AND voided_at IS NULL
              AND created_at>=? AND created_at<? GROUP BY store_id) r ON r.store_id=s.id
            GROUP BY s.id,s.name,s.enabled ORDER BY gmv DESC,s.name LIMIT 1000''',(start,end,start,end))
        return jsonify(months=months,month=selected,ranking=ranking)

    @app.put('/api/platform/stores/<int:sid>')
    @platform
    def platform_store(sid):
        value=h.data()
        store=h.one('SELECT * FROM stores WHERE id=?',(sid,))
        if not store:
            abort(404,description='Loja não encontrada.')
        commission=h.integer(value,'commission_bps',maximum=10000)
        fee=h.integer(value,'monthly_fee')
        enabled=h.boolean(value,'enabled',bool(store['enabled']))
        promo_fee=value.get('promo_fee',store['promo_fee'])
        if promo_fee is not None:
            promo_fee=h.integer({'promo_fee':promo_fee},'promo_fee')
        promo_until=h.text(value,'promo_until',0,10) if 'promo_until' in value else store['promo_until']
        promo_label=h.text(value,'promo_label',0,80) if 'promo_label' in value else store['promo_label']
        if promo_until:
            try:
                datetime.strptime(promo_until,'%Y-%m-%d')
            except ValueError:
                abort(400,description='Data final da promoção inválida.')
        if promo_fee is not None and not promo_until:
            abort(400,description='Informe até quando vale a promoção.')
        with h.transaction() as conn:
            conn.execute('''UPDATE stores SET commission_bps=?,monthly_fee=?,enabled=?,promo_fee=?,promo_until=?,promo_label=?,
                blocked_reason=CASE WHEN ?=1 THEN '' ELSE blocked_reason END WHERE id=?''',
                (commission,fee,enabled,promo_fee,promo_until if promo_fee is not None else '',promo_label if promo_fee is not None else '',enabled,sid))
            if not enabled:
                conn.execute('UPDATE stores SET open=0 WHERE id=?',(sid,))
            audit('store.plan',json.dumps({'commission_bps':commission,'monthly_fee':fee,'enabled':enabled,
                                           'promo_fee':promo_fee,'promo_until':promo_until}),sid)
        return jsonify(ok=True)

    @app.post('/api/platform/stores/<int:sid>/block')
    @platform
    def platform_block(sid):
        value=h.data()
        blocked=h.boolean(value,'blocked')
        reason=h.text(value,'reason',3 if blocked else 0,300)
        if not h.one('SELECT id FROM stores WHERE id=?',(sid,)):
            abort(404,description='Loja não encontrada.')
        with h.transaction() as conn:
            if blocked:
                conn.execute('UPDATE stores SET enabled=0,open=0,blocked_reason=? WHERE id=?',(reason,sid))
            else:
                conn.execute("UPDATE stores SET enabled=1,blocked_reason='' WHERE id=?",(sid,))
            audit('store.block' if blocked else 'store.unblock',reason,sid)
        return jsonify(ok=True)

    @app.get('/api/platform/notices')
    @platform
    def platform_notices():
        return jsonify(notices=h.rows('SELECT * FROM platform_notices ORDER BY id DESC LIMIT 100'))

    @app.post('/api/platform/notices')
    @platform
    def create_notice():
        value=h.data()
        kind=value.get('kind','info')
        if kind not in ('info','promo','alert'):
            abort(400,description='Tipo de aviso inválido.')
        expires=h.text(value,'expires',0,10)
        if expires:
            try:
                datetime.strptime(expires,'%Y-%m-%d')
            except ValueError:
                abort(400,description='Validade inválida.')
        with h.transaction() as conn:
            nid=conn.execute('INSERT INTO platform_notices(title,body,kind,expires,created_at) VALUES(?,?,?,?,?)',
                (h.text(value,'title',3,100),h.text(value,'body',3,600),kind,expires,h.now())).lastrowid
            audit('notice.create',str(nid))
        return jsonify(id=nid),201

    @app.patch('/api/platform/notices/<int:nid>')
    @platform
    def toggle_notice(nid):
        if not h.one('SELECT id FROM platform_notices WHERE id=?',(nid,)):
            abort(404,description='Aviso não encontrado.')
        active=h.boolean(h.data(),'active')
        with h.transaction() as conn:
            conn.execute('UPDATE platform_notices SET active=? WHERE id=?',(active,nid))
            audit('notice.toggle',str(nid))
        return jsonify(ok=True)

    @app.get('/api/admin/notices')
    @h.owner
    def merchant_notices():
        today=datetime.now(ZONE).date().isoformat()
        return jsonify(notices=h.rows("SELECT id,title,body,kind,created_at FROM platform_notices WHERE active=1 AND (expires='' OR expires>=?) ORDER BY id DESC LIMIT 5",(today,)),
                       blocked_reason='' if g.store['enabled'] else (g.store['blocked_reason'] or 'Loja suspensa pela plataforma.'))

    @app.post('/api/platform/ledger')
    @platform
    def platform_ledger():
        value=h.data()
        key=request.headers.get('Idempotency-Key','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',key):
            abort(400,description='Identificador de lançamento inválido.')
        digest=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        kind=value.get('kind')
        if kind not in ('receipt','expense'):
            abort(400,description='Tipo de lançamento inválido.')
        sid=value.get('store_id')
        if sid is not None:
            sid=h.integer(value,'store_id',minimum=1)
            if not h.one('SELECT id FROM stores WHERE id=?',(sid,)):
                abort(404,description='Loja não encontrada.')
        if kind=='receipt' and not sid:
            abort(400,description='Selecione a loja que efetuou o pagamento.')
        with h.transaction() as conn:
            previous=h.one('SELECT id,payload_hash FROM platform_ledger WHERE idempotency_key=?',(key,))
            if previous:
                if previous['payload_hash']!=digest:
                    abort(409,description='Este identificador já pertence a outro lançamento.')
                return jsonify(id=previous['id'],duplicate=True)
            lid=conn.execute('INSERT INTO platform_ledger(store_id,kind,description,amount,created_at,idempotency_key,payload_hash) VALUES(?,?,?,?,?,?,?)',
                (sid,kind,h.text(value,'description',3,200),h.integer(value,'amount',minimum=1),h.now(),key,digest)).lastrowid
            audit('ledger.'+kind,str(lid),sid)
        return jsonify(id=lid),201

    @app.delete('/api/platform/ledger/<int:lid>')
    @platform
    def void_platform_ledger(lid):
        with h.transaction() as conn:
            entry=h.one('SELECT * FROM platform_ledger WHERE id=?',(lid,))
            if not entry:
                abort(404,description='Lançamento não encontrado.')
            if not entry['voided_at']:
                conn.execute('UPDATE platform_ledger SET voided_at=? WHERE id=?',(h.now(),lid))
                audit('ledger.void',str(lid),entry['store_id'])
        return jsonify(ok=True)

    @app.get('/api/admin/integrations')
    @h.owner
    def integrations():
        return jsonify(base_url=app.config['PUBLIC_URL'] or request.host_url.rstrip('/'), scopes=sorted(SCOPES),
            keys=h.rows('SELECT id,name,prefix,scopes,created_at,last_used_at,revoked_at FROM api_keys WHERE store_id=? ORDER BY id DESC',(g.store['id'],)),
            deliveries=h.rows('''SELECT l.id,l.order_id,o.number,l.external_id,l.provider,l.status,l.updated_at
             FROM delivery_links l JOIN orders o ON o.id=l.order_id WHERE l.store_id=? ORDER BY l.id DESC LIMIT 100''',(g.store['id'],)))

    @app.post('/api/admin/integrations/keys')
    @h.owner
    def create_key():
        value=h.data()
        scopes=value.get('scopes',[])
        if not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) or s not in SCOPES for s in scopes):
            abort(400,description='Selecione permissões válidas.')
        if h.one('SELECT COUNT(*) FROM api_keys WHERE store_id=? AND revoked_at IS NULL',(g.store['id'],))[0]>=10:
            abort(409,description='Revogue uma chave antes de criar outra (limite de 10 ativas).')
        token='sca_'+secrets.token_urlsafe(32)
        with h.transaction() as conn:
            kid=conn.execute('INSERT INTO api_keys(store_id,name,token_hash,prefix,scopes,created_at) VALUES(?,?,?,?,?,?)',
                (g.store['id'],h.text(value,'name',2,80),hashlib.sha256(token.encode()).hexdigest(),token[:12],json.dumps(sorted(set(scopes))),h.now())).lastrowid
            audit('key.create',str(kid),g.store['id'])
        return jsonify(id=kid,token=token),201

    @app.delete('/api/admin/integrations/keys/<int:kid>')
    @h.owner
    def revoke_key(kid):
        h.owned('api_keys',kid)
        with h.transaction() as conn:
            conn.execute('UPDATE api_keys SET revoked_at=? WHERE id=? AND store_id=?',(h.now(),kid,g.store['id']))
            audit('key.revoke',str(kid),g.store['id'])
        return jsonify(ok=True)

    def partner_auth():
        header=request.headers.get('Authorization','')
        if not re.fullmatch(r'Bearer sca_[A-Za-z0-9_-]{43}',header):
            abort(401,description='Informe Authorization: Bearer com uma chave de integração.')
        token=header[7:]
        key=h.one('SELECT * FROM api_keys WHERE token_hash=? AND revoked_at IS NULL',(hashlib.sha256(token.encode()).hexdigest(),))
        if not key:
            abort(401,description='Chave inválida ou revogada.')
        store=h.one('SELECT * FROM stores WHERE id=? AND enabled=1',(key['store_id'],))
        if not store:
            abort(403,description='Loja indisponível.')
        # This limit is independent of the caller IP to prevent distributed key abuse.
        h.limited('partner-key-'+str(key['id']),120,60,per_ip=False)
        h.db().execute('UPDATE api_keys SET last_used_at=? WHERE id=?',(h.now(),key['id']))
        g.api_key,g.store=key,store

    app.extensions['partner_auth']=partner_auth

    def scoped(scope):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args,**kwargs):
                if scope not in json.loads(g.api_key['scopes']):
                    abort(403,description='Esta chave não tem a permissão '+scope+'.')
                return fn(*args,**kwargs)
            return wrapped
        return decorator

    def partner_order(order):
        return {'id':order['id'],'number':order['number'],'status':order['status'],'customer':order['customer'],
                'phone':order['phone'],'address':order['address'],'mode':order['mode'],
                'total':order['total'],'delivery_fee':order['delivery_fee'],'payment':order['payment'],
                'paid':bool(order['paid']),'notes':order['notes'],'created_at':order['created_at'],
                'pickup':{'name':g.store['name'],'address':g.store['address'],'phone':g.store['phone']},
                'items':h.rows('SELECT name,quantity,notes FROM order_items WHERE order_id=?',(order['id'],))}

    @app.get('/api/v1/store')
    @scoped('orders:read')
    def partner_store():
        return jsonify(id=g.store['id'],name=g.store['name'],slug=g.store['slug'],currency='BRL',money_unit='centavos',api_version=1)

    @app.get('/api/v1/deliveries')
    @scoped('orders:read')
    def partner_deliveries():
        raw=request.args.get('after','0')
        if not raw.isdigit() or len(raw)>16:
            abort(400,description='Cursor inválido.')
        result=h.rows('''SELECT o.* FROM orders o WHERE o.store_id=? AND o.mode='delivery' AND o.id>?
            AND o.status IN ('ready','delivering') ORDER BY o.id LIMIT 100''',(g.store['id'],int(raw)))
        return jsonify(deliveries=[partner_order(o) for o in result],next_after=result[-1]['id'] if len(result)==100 else None)

    @app.post('/api/v1/deliveries/<int:oid>/claim')
    @scoped('deliveries:write')
    def partner_claim(oid):
        value=h.data()
        external=h.text(value,'external_id',1,100)
        provider=h.text(value,'provider',2,40)
        if not re.fullmatch(r'[a-z0-9_-]+',provider):
            abort(400,description='Identificador de parceiro inválido.')
        cost=value.get('delivery_cost')
        if cost is not None:
            cost=h.integer(value,'delivery_cost')
        with h.transaction() as conn:
            order=h.owned('orders',oid)
            previous=h.one('SELECT * FROM delivery_links WHERE order_id=?',(oid,))
            if previous:
                if previous['key_id']!=g.api_key['id'] or previous['external_id']!=external or previous['provider']!=provider:
                    abort(409,description='Este pedido já está vinculado a outra entrega.')
                return jsonify(id=previous['id'],status=previous['status'],duplicate=True)
            if order['mode']!='delivery' or order['status']!='ready':
                abort(409,description='Somente pedidos de entrega prontos podem ser vinculados.')
            stamp=h.now()
            lid=conn.execute('INSERT INTO delivery_links(store_id,order_id,key_id,external_id,provider,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (g.store['id'],oid,g.api_key['id'],external,provider,stamp,stamp)).lastrowid
            if cost is not None:
                conn.execute('UPDATE orders SET delivery_cost=? WHERE id=?',(cost,oid))
        return jsonify(id=lid,status='claimed'),201

    @app.post('/api/v1/deliveries/<int:oid>/events')
    @scoped('deliveries:write')
    def partner_event(oid):
        value=h.data()
        event=h.text(value,'event_id',8,100)
        target=value.get('status')
        if target not in ('delivering','completed'):
            abort(400,description='Use delivering ou completed.')
        digest=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with h.transaction() as conn:
            order=h.owned('orders',oid)
            link=h.one('SELECT * FROM delivery_links WHERE order_id=? AND store_id=? AND key_id=?',(oid,g.store['id'],g.api_key['id']))
            if not link:
                abort(403,description='Vincule a entrega com esta chave antes de enviar eventos.')
            old=h.one('SELECT * FROM integration_events WHERE key_id=? AND event_id=?',(g.api_key['id'],event))
            if old:
                if old['order_id']!=oid or old['payload_hash']!=digest:
                    abort(409,description='Este event_id já foi usado com outros dados.')
                return jsonify(ok=True,duplicate=True)
            if order['status']!=target:
                if (order['status'],target) not in (('ready','delivering'),('delivering','completed')):
                    abort(409,description='Transição de entrega inválida.')
                conn.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',(target,h.now(),oid))
                conn.execute('INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)',(oid,target,h.now()))
            conn.execute('UPDATE delivery_links SET status=?,updated_at=? WHERE id=?',(target,h.now(),link['id']))
            conn.execute('INSERT INTO integration_events(key_id,order_id,event_id,payload_hash,created_at) VALUES(?,?,?,?,?)',
                         (g.api_key['id'],oid,event,digest,h.now()))
        return jsonify(ok=True)

    @app.cli.command('grant-platform-admin')
    @click.option('--email',required=True)
    def grant_platform_admin(email):
        """Operator-only grant. Self-registration can never set this role."""
        user=h.one('SELECT id FROM users WHERE email=?',(email.lower().strip(),))
        if not user:
            raise click.ClickException('Conta não encontrada.')
        h.db().execute('UPDATE users SET platform_admin=1 WHERE id=?',(user['id'],))
        click.echo('Acesso ao painel da plataforma liberado.')
