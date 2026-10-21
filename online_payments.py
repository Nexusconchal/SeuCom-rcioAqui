"""Server-verified Pix and hosted card checkout for restaurant orders.

The attempt is committed before contacting the provider. A retry preserves its
identity, including after an interrupted HTTP response. Provider payloads and
checkout return parameters never directly become proof of payment.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from payments import PaymentError, unseal, safe_checkout_url

DDL = """
CREATE TABLE IF NOT EXISTS order_payment_attempts (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 order_id INTEGER NOT NULL REFERENCES orders(id), kind TEXT NOT NULL,
 attempt INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
 external_reference TEXT NOT NULL UNIQUE, collector_id TEXT NOT NULL, credential TEXT NOT NULL DEFAULT '',
 amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'creating',
 provider_id TEXT NOT NULL DEFAULT '', preference_id TEXT NOT NULL DEFAULT '',
 checkout_url TEXT NOT NULL DEFAULT '', pix_code TEXT NOT NULL DEFAULT '',
 expires_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(order_id,kind,attempt)
);
CREATE INDEX IF NOT EXISTS ix_order_payment_attempts_order ON order_payment_attempts(store_id,order_id,id);
CREATE TABLE IF NOT EXISTS order_payment_transactions (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 order_id INTEGER NOT NULL REFERENCES orders(id), attempt_id INTEGER NOT NULL REFERENCES order_payment_attempts(id),
 provider_id TEXT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL,
 refunded INTEGER NOT NULL DEFAULT 0, fee INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL, approved_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
 refund_key TEXT NOT NULL DEFAULT '', refund_state TEXT NOT NULL DEFAULT '', refund_started_at TEXT NOT NULL DEFAULT '',
 UNIQUE(store_id,provider_id)
);
CREATE INDEX IF NOT EXISTS ix_order_payment_transactions_order ON order_payment_transactions(store_id,order_id,id);
"""

ONLINE_METHODS = ('pix_online', 'card_online')
FINAL = ('approved', 'refunded', 'charged_back', 'cancelled', 'rejected')
PROVIDER_STATUSES = {'pending','approved','authorized','in_process','in_mediation','rejected','cancelled','refunded','charged_back'}


def cents(value):
    if isinstance(value, bool):raise PaymentError('Valor de pagamento inválido.')
    try:
        number = Decimal(str(value)) * 100
        if not number.is_finite() or number != number.to_integral_value() or number < 0:
            raise ValueError()
        return int(number)
    except (InvalidOperation, ValueError, TypeError):
        raise PaymentError('Valor de pagamento inválido.') from None


def stamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.astimezone(timezone.utc).isoformat(timespec='seconds') if d.tzinfo else ''
    except (ValueError, TypeError):return ''


def register_online_payments(app, helpers):
    h = SimpleNamespace(**helpers)
    def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
    def mp():return app.extensions['mercadopago']
    def token(store,attempt=None):
        sealed=attempt['credential'] if attempt and attempt.get('credential') else store['mp_token']
        result=unseal(app.config['SECRET_KEY'],sealed)
        if not result:raise PaymentError('Conecte a conta Mercado Pago da loja para receber online.')
        return result
    def store_order(sid,oid):
        store=h.one('SELECT * FROM stores WHERE id=?',(sid,))
        order=h.one('SELECT * FROM orders WHERE id=? AND store_id=?',(oid,sid))
        if not store or not order:raise PaymentError('Pedido não encontrado nesta loja.')
        return store,order
    def attempts(order):
        return h.rows('SELECT * FROM order_payment_attempts WHERE store_id=? AND order_id=? ORDER BY id DESC',(order['store_id'],order['id']))
    def collector(store):
        account=mp().me(token(store))
        value=str(account.get('id',''))
        if not value.isdigit():raise PaymentError('Não foi possível conferir o recebedor do pagamento.')
        return value

    def legacy(order,store):
        """Preserve a Pix issued before the attempt ledger was introduced."""
        if order['payment']!='pix_online' or not order['pix_provider_id']:return
        if h.one('SELECT id FROM order_payment_attempts WHERE store_id=? AND provider_id=?',(store['id'],order['pix_provider_id'])):return
        account=collector(store)
        with h.transaction() as conn:
            if conn.execute('SELECT id FROM order_payment_attempts WHERE store_id=? AND provider_id=?',(store['id'],order['pix_provider_id'])).fetchone():return
            conn.execute('''INSERT INTO order_payment_attempts(store_id,order_id,kind,attempt,idempotency_key,external_reference,
                collector_id,credential,amount,status,provider_id,pix_code,expires_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (store['id'],order['id'],'pix',1,f"legacy-pix-{store['id']}-{order['id']}",f"sca-{store['id']}-{order['id']}",
                 account,store['mp_token'],order['total'],'pending',str(order['pix_provider_id']),order['pix_code'],order['pix_expires'],order['created_at'],now()))

    def state(order):
        current=h.one('SELECT * FROM orders WHERE id=? AND store_id=?',(order['id'],order['store_id'])) or order
        rows=attempts(current)
        transactions=h.rows('SELECT * FROM order_payment_transactions WHERE store_id=? AND order_id=? ORDER BY id DESC',(order['store_id'],order['id']))
        latest=rows[0] if rows else None
        live=[p for p in transactions if p['status']=='approved' and p['amount']>p['refunded']]
        review=bool((current['status']=='cancelled' and live) or len(live)>1 or any(p['refunded'] and p['refunded']<p['amount'] for p in transactions) or any(p['status']=='in_mediation' for p in transactions))
        status='approved' if current['paid'] else latest['status'] if latest else 'not_started'
        if latest and latest['expires_at'] and latest['expires_at']<now() and status=='pending':status='expired'
        if current['status']=='cancelled' and not live:status='cancelled'
        if review:status='review'
        email=current['payer_email'] if 'payer_email' in current.keys() else ''
        return {'method':current['payment'],'status':status,'paid':bool(current['paid']),
                'code':latest['pix_code'] if latest and latest['kind']=='pix' and not current['paid'] and status=='pending' else '',
                'expires':latest['expires_at'] if latest else '',
                'checkout_url':safe_checkout_url(latest['checkout_url']) if latest and not current['paid'] and status=='pending' else '',
                'can_retry':not current['paid'] and current['status']!='cancelled' and not review and len(rows)<5 and status not in ('creating','uncertain'),
                'review':review,'needs_email':current['payment'] in ONLINE_METHODS and not email and not current['paid']}

    def verify(info,attempt,pid):
        if not isinstance(info,dict) or str(info.get('id',''))!=str(pid):raise PaymentError('Identificação do pagamento não confere.')
        if info.get('currency_id')!='BRL' or str(info.get('collector_id',''))!=attempt['collector_id']:
            raise PaymentError('Moeda ou recebedor do pagamento não confere.')
        if info.get('external_reference')!=attempt['external_reference'] or cents(info.get('transaction_amount'))!=attempt['amount']:
            raise PaymentError('O pagamento não corresponde ao valor deste pedido.')
        if attempt['kind']=='pix' and (info.get('payment_method_id')!='pix' or str(pid)!=attempt['provider_id']):
            raise PaymentError('A cobrança Pix não corresponde a esta tentativa.')
        # Checkout Pro cannot exclude Mercado Pago account balance. It remains a
        # provider-hosted alternative; other payment types are rejected here.
        if attempt['kind']=='card' and info.get('payment_type_id') not in ('credit_card','account_money'):
            raise PaymentError('A modalidade do pagamento online não confere.')
        status=info.get('status')
        if not isinstance(status,str) or status not in PROVIDER_STATUSES:raise PaymentError('Situação de pagamento desconhecida.')
        refunded=cents(info.get('transaction_amount_refunded',0))
        if status in ('refunded','charged_back'):refunded=attempt['amount']
        if refunded>attempt['amount']:raise PaymentError('Valor de estorno inválido.')
        fees=info.get('fee_details') or []
        if not isinstance(fees,list) or any(not isinstance(x,dict) for x in fees):raise PaymentError('Taxa de pagamento inválida.')
        fee=sum(cents(x.get('amount')) for x in fees)
        return status,refunded,fee

    def reconcile(attempt,info,pid):
        status,refunded,fee=verify(info,attempt,pid)
        auto=False;sid,oid=attempt['store_id'],attempt['order_id']
        with h.transaction() as conn:
            order=conn.execute('SELECT * FROM orders WHERE id=? AND store_id=?',(oid,sid)).fetchone()
            if not order:return status
            if order['total']!=attempt['amount']:raise PaymentError('O total do pedido mudou. Confira a cobrança com a loja.')
            prior=conn.execute('SELECT * FROM order_payment_transactions WHERE store_id=? AND provider_id=?',(sid,str(pid))).fetchone()
            if prior and (prior['order_id']!=oid or prior['attempt_id']!=attempt['id']):raise PaymentError('Pagamento já vinculado a outro pedido.')
            # A response started before a refund must never resurrect paid money.
            if prior and prior['status'] in ('refunded','charged_back') and status not in ('refunded','charged_back'):
                return prior['status']
            if prior and prior['status']=='approved' and status not in ('approved','refunded','charged_back','in_mediation'):
                return prior['status']
            refunded=max(refunded,prior['refunded'] if prior else 0)
            approved_at=stamp(info.get('date_approved')) or (prior['approved_at'] if prior else '')
            conn.execute('''INSERT INTO order_payment_transactions(store_id,order_id,attempt_id,provider_id,kind,amount,refunded,fee,status,approved_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(store_id,provider_id) DO UPDATE SET
                refunded=excluded.refunded,fee=excluded.fee,status=excluded.status,approved_at=excluded.approved_at,updated_at=excluded.updated_at''',
                (sid,oid,attempt['id'],str(pid),attempt['kind'],attempt['amount'],refunded,fee,status,approved_at,now()))
            conn.execute('UPDATE order_payment_attempts SET status=?,updated_at=? WHERE id=?',(status,now(),attempt['id']))
            rows=conn.execute('SELECT * FROM order_payment_transactions WHERE store_id=? AND order_id=?',(sid,oid)).fetchall()
            net=sum(p['amount']-p['refunded'] for p in rows if p['status']=='approved')
            paid=net>=order['total'] and order['total']>0
            total_fee=sum(p['fee'] for p in rows if p['status']=='approved')
            conn.execute('UPDATE orders SET paid=?,payment_fee=?,pix_checked_at=?,updated_at=? WHERE id=?',(int(paid),total_fee,now(),now(),oid))
            store=conn.execute('SELECT auto_accept FROM stores WHERE id=?',(sid,)).fetchone()
            if paid and order['status']=='new' and not order['scheduled_for'] and store['auto_accept']:
                conn.execute("UPDATE orders SET status='preparing' WHERE id=? AND status='new'",(oid,))
                conn.execute("UPDATE order_items SET kitchen_state='preparing' WHERE order_id=? AND kitchen_state='new'",(oid,))
                conn.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,'preparing',?)",(oid,now()))
                auto=True
        if auto and app.extensions.get('on_status'):
            try:app.extensions['on_status'](sid,oid,'preparing')
            except Exception:app.logger.warning('Pagamento confirmado; aviso de preparo pendente para pedido %s',oid)
        return status

    def sync(order,store):
        if order['payment'] not in ONLINE_METHODS:return ''
        legacy(order,store)
        rows=attempts(order)
        ids=[]
        for attempt in rows:
            if attempt['kind']=='pix' and attempt['provider_id']:ids.append((attempt,str(attempt['provider_id'])))
            elif attempt['kind']=='card':
                result=mp().search_payments(token(store,attempt),attempt['external_reference'])
                records=result.get('results',[]) if isinstance(result,dict) else []
                if not isinstance(records,list):raise PaymentError('Consulta de pagamento inválida.')
                for value in records[:100]:
                    pid=str(value.get('id','')) if isinstance(value,dict) else ''
                    if pid.isdigit():ids.append((attempt,pid))
        for attempt,pid in ids:
            info=mp().get_payment(token(store,attempt),pid)
            reconcile(attempt,info,pid)
        h.db().execute('UPDATE orders SET pix_checked_at=? WHERE id=?',(now(),order['id']))
        return state(order)['status']

    def webhook(store,payment_id):
        pid=str(payment_id)
        if not re.fullmatch(r'\d{1,25}',pid):return False
        bound=h.one('''SELECT a.* FROM order_payment_attempts a LEFT JOIN order_payment_transactions t ON t.attempt_id=a.id
            WHERE a.store_id=? AND (a.provider_id=? OR t.provider_id=?) ORDER BY a.id DESC LIMIT 1''',(store['id'],pid,pid))
        info=mp().get_payment(token(store,dict(bound) if bound else None),pid)
        if not isinstance(info,dict):return False
        attempt=h.one('SELECT * FROM order_payment_attempts WHERE store_id=? AND external_reference=?',(store['id'],info.get('external_reference','')))
        if not attempt:
            order=h.one("SELECT * FROM orders WHERE store_id=? AND pix_provider_id=? AND payment='pix_online'",(store['id'],pid))
            if not order:return False
            legacy(order,store)
            attempt=h.one('SELECT * FROM order_payment_attempts WHERE store_id=? AND provider_id=?',(store['id'],pid))
        if not attempt:return False
        reconcile(attempt,info,pid)
        return True

    def recover_preference(store,attempt):
        response=mp().search_preferences(token(store,attempt),attempt['external_reference'])
        values=response.get('elements',response.get('results',[])) if isinstance(response,dict) else []
        if not isinstance(values,list):return None
        matches=[v for v in values[:100] if isinstance(v,dict) and v.get('external_reference')==attempt['external_reference'] and str(v.get('collector_id',''))==attempt['collector_id']]
        if len(matches)!=1:return None
        return mp().get_preference(token(store,attempt),matches[0]['id'])

    def create(sid,oid,kind='pix'):
        if kind not in ('pix','card'):raise PaymentError('Forma de pagamento online inválida.')
        store,order=store_order(sid,oid)
        if order['payment']!=('pix_online' if kind=='pix' else 'card_online'):raise PaymentError('Esta cobrança usa outra forma de pagamento.')
        if order['paid'] or order['status']=='cancelled' or order['total']<=0:raise PaymentError('Este pedido não precisa de nova cobrança.')
        if attempts(order) or order['pix_provider_id']:
            sync(order,store)
            store,order=store_order(sid,oid)
            if order['paid']:return state(order)
            if state(order)['review']:raise PaymentError('A cobrança precisa de conferência pela loja antes de outra tentativa.')
        account=collector(store)
        reference='';recover=False
        with h.transaction() as conn:
            fresh=conn.execute('SELECT * FROM orders WHERE id=? AND store_id=?',(oid,sid)).fetchone()
            configured=conn.execute('SELECT mp_token FROM stores WHERE id=?',(sid,)).fetchone()
            if not configured or not configured['mp_token'] or configured['mp_token']!=store['mp_token']:
                raise PaymentError('A conexão de pagamento mudou. Confira a conta da loja e tente novamente.')
            if fresh['paid'] or fresh['status']=='cancelled':raise PaymentError('Este pedido não precisa de nova cobrança.')
            last=conn.execute('SELECT * FROM order_payment_attempts WHERE order_id=? AND kind=? ORDER BY id DESC LIMIT 1',(oid,kind)).fetchone()
            if last and last['collector_id']!=account:raise PaymentError('A conta recebedora mudou. Confira as cobranças anteriores com a loja.')
            if last and last['amount']!=fresh['total']:raise PaymentError('O total mudou; confira o pedido com a loja antes de pagar.')
            if last and last['status']=='pending' and last['expires_at']>now():return state(fresh)
            if last and last['status']=='creating' and last['updated_at']>(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(timespec='seconds'):
                return state(fresh)
            if last and last['status'] in ('creating','uncertain'):
                conn.execute("UPDATE order_payment_attempts SET status='creating',updated_at=? WHERE id=?",(now(),last['id']))
                attempt=dict(last);recover=True
            else:
                count=conn.execute('SELECT COUNT(*) FROM order_payment_attempts WHERE order_id=? AND kind=?',(oid,kind)).fetchone()[0]
                if count>=5:raise PaymentError('Limite de tentativas atingido. Fale com a loja.')
                email=fresh['payer_email'] if 'payer_email' in fresh.keys() else ''
                if not isinstance(email,str) or not re.fullmatch(r'[^\s@]{1,120}@[^\s@]{1,120}\.[^\s@]{2,30}',email) or len(email)>254:
                    raise PaymentError('Informe o e-mail do pagador para iniciar o pagamento online.')
                key=secrets.token_hex(24);reference=f'sca-{sid}-{oid}-{kind}-{key}'
                expires=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(timespec='seconds')
                aid=conn.execute('''INSERT INTO order_payment_attempts(store_id,order_id,kind,attempt,idempotency_key,external_reference,collector_id,credential,amount,status,expires_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,'creating',?,?,?)''',(sid,oid,kind,count+1,key,reference,account,store['mp_token'],fresh['total'],expires,now(),now())).lastrowid
                attempt=dict(conn.execute('SELECT * FROM order_payment_attempts WHERE id=?',(aid,)).fetchone())
        # All provider calls happen after the attempt claim has committed.
        try:
            if kind=='pix':
                email=order['payer_email'] if 'payer_email' in order.keys() else ''
                if not email:raise PaymentError('Informe o e-mail do pagador para gerar o Pix.')
                payload={'transaction_amount':attempt['amount']/100,'payment_method_id':'pix',
                         'description':f"Pedido #{order['number']} - {store['name']}"[:200],
                         'external_reference':attempt['external_reference'],'date_of_expiration':attempt['expires_at'],
                         'payer':{'email':email,'first_name':order['customer'].split(' ')[0][:40]}}
                base=h.public_base()
                if base.startswith('https://') and store['mp_webhook_key']:payload['notification_url']=base+'/webhooks/mercadopago/'+store['mp_webhook_key']
                result=None
                if recover:
                    found=mp().search_payments(token(store,attempt),attempt['external_reference'])
                    values=found.get('results',[]) if isinstance(found,dict) else []
                    if not isinstance(values,list):raise PaymentError('Consulta de pagamento inválida.')
                    matches=[p for p in values if isinstance(p,dict) and p.get('external_reference')==attempt['external_reference']]
                    if len(matches)>1:raise PaymentError('Há cobranças em conferência. Fale com a loja antes de tentar novamente.')
                    if matches:result=mp().get_payment(token(store,attempt),str(matches[0].get('id','')))
                    elif attempt['expires_at']<=now():
                        raise PaymentError('A tentativa anterior precisa ser conferida pela loja antes de gerar outro Pix.')
                if result is None:result=mp().create_pix(token(store,attempt),payload,attempt['idempotency_key'])
                pid=str(result.get('id',''));code=((result.get('point_of_interaction') or {}).get('transaction_data') or {}).get('qr_code','')
                if not pid.isdigit() or not isinstance(code,str) or len(code)>10000:raise PaymentError('O Mercado Pago não devolveu o código Pix.')
                # A valid ID and QR alone do not establish whose charge this is.
                # Fetch the canonical payment before exposing either to a payer.
                info=mp().get_payment(token(store,attempt),pid)
                bound={**attempt,'provider_id':pid}
                status,_,_=verify(info,bound,pid)
                if not code and status not in FINAL:raise PaymentError('O Mercado Pago não devolveu o código Pix.')
                with h.transaction() as conn:
                    conn.execute("UPDATE order_payment_attempts SET provider_id=?,pix_code=?,status=?,updated_at=? WHERE id=?",(pid,code,status,now(),attempt['id']))
                    conn.execute('UPDATE orders SET pix_provider_id=?,pix_code=?,pix_expires=?,pix_attempts=?,pix_checked_at=? WHERE id=?',
                                 (pid,code,attempt['expires_at'],attempt['attempt'],now(),oid))
                reconcile(bound,info,pid)
            else:
                result=recover_preference(store,attempt) if recover else None
                if recover and not result:raise PaymentError('A cobrança anterior está em conferência. Tente verificar novamente em instantes.')
                if not result:
                    base=h.public_base();back=base+'/pedido/'+order['tracking_token']
                    payload={'payer':{'email':order['payer_email']},'items':[{'id':str(oid),'title':f"Pedido #{order['number']} - {store['name']}"[:200],
                                       'quantity':1,'unit_price':attempt['amount']/100,'currency_id':'BRL'}],
                             'external_reference':attempt['external_reference'],'back_urls':{'success':back,'failure':back,'pending':back},
                             'auto_return':'approved','binary_mode':True,'expires':True,'expiration_date_to':attempt['expires_at'],
                             'payment_methods':{'excluded_payment_types':[{'id':v} for v in ('ticket','bank_transfer','debit_card','prepaid_card','atm','digital_currency')],'installments':1}}
                    if base.startswith('https://') and store['mp_webhook_key']:payload['notification_url']=base+'/webhooks/mercadopago/'+store['mp_webhook_key']
                    result=mp().create_preference(token(store,attempt),payload,attempt['idempotency_key'])
                pref=str(result.get('id',''));url=safe_checkout_url(result.get('sandbox_init_point') if token(store,attempt).startswith('TEST-') else result.get('init_point'))
                if not pref or len(pref)>200 or not url or str(result.get('collector_id',''))!=attempt['collector_id']:
                    raise PaymentError('O serviço não devolveu um checkout seguro para esta loja.')
                if result.get('external_reference')!=attempt['external_reference']:
                    raise PaymentError('A preferência não corresponde a este pedido.')
                pref_items=result.get('items',[])
                if not isinstance(pref_items,list) or not pref_items or any(not isinstance(i,dict) or i.get('currency_id')!='BRL' or type(i.get('quantity')) is not int or i['quantity']<1 for i in pref_items):
                    raise PaymentError('Não foi possível conferir os itens do checkout.')
                if sum(cents(i.get('unit_price'))*i['quantity'] for i in pref_items)!=attempt['amount']:
                    raise PaymentError('O valor do checkout não corresponde a este pedido.')
                with h.transaction() as conn:
                    conn.execute("UPDATE order_payment_attempts SET preference_id=?,checkout_url=?,status='pending',updated_at=? WHERE id=?",(pref,url,now(),attempt['id']))
        except Exception as error:
            h.db().execute("UPDATE order_payment_attempts SET status='uncertain',updated_at=? WHERE id=? AND status='creating'",(now(),attempt['id']))
            current=h.one('SELECT * FROM orders WHERE id=? AND store_id=?',(oid,sid))
            if current and current['status']=='cancelled':
                try:cancel_pending(store,current)
                except PaymentError:pass
            if isinstance(error,PaymentError):raise
            raise PaymentError('Não foi possível iniciar o pagamento agora. Sua tentativa será conferida antes de repetir.') from None
        current=h.one('SELECT * FROM orders WHERE id=? AND store_id=?',(oid,sid))
        if current and current['status']=='cancelled':
            # Cancellation may have committed while the provider HTTP call was
            # in flight. Keep its identity, then expire/cancel outside the TX.
            cancel_pending(store,current)
        return state(order)

    def cancel_pending(store,order):
        legacy(order,store)
        for attempt in attempts(order):
            if attempt['status'] in FINAL:continue
            if attempt['kind']=='pix' and not attempt['provider_id']:
                try:
                    result=mp().search_payments(token(store,attempt),attempt['external_reference'])
                    values=result.get('results',[]) if isinstance(result,dict) else []
                    matches=[p for p in values if isinstance(p,dict) and p.get('external_reference')==attempt['external_reference']] if isinstance(values,list) else []
                    if len(matches)!=1:continue
                    pid=str(matches[0].get('id',''))
                    if not pid.isdigit():continue
                    info=mp().get_payment(token(store,attempt),pid)
                    attempt={**attempt,'provider_id':pid}
                    status,_,_=verify(info,attempt,pid)
                    h.db().execute('UPDATE order_payment_attempts SET provider_id=?,status=?,updated_at=? WHERE id=?',(pid,status,now(),attempt['id']))
                    reconcile(attempt,info,pid)
                    attempt['status']=status
                except PaymentError:continue
            elif attempt['kind']=='card' and not attempt['preference_id']:
                try:
                    pref=recover_preference(store,attempt)
                    if not pref:continue
                    if str(pref.get('collector_id',''))!=attempt['collector_id'] or pref.get('external_reference')!=attempt['external_reference']:continue
                    attempt={**attempt,'preference_id':str(pref['id'])}
                    h.db().execute('UPDATE order_payment_attempts SET preference_id=?,updated_at=? WHERE id=?',(attempt['preference_id'],now(),attempt['id']))
                except PaymentError:continue
            if attempt['kind']=='pix' and attempt['provider_id'] and attempt['status'] not in FINAL:
                try:
                    mp().cancel(token(store,attempt),attempt['provider_id'])
                    info=mp().get_payment(token(store,attempt),attempt['provider_id'])
                    reconcile(attempt,info,attempt['provider_id'])
                except PaymentError:continue
            elif attempt['kind']=='card' and attempt['preference_id'] and attempt['status'] not in FINAL:
                try:mp().update_preference(token(store,attempt),attempt['preference_id'],{'expires':True,'expiration_date_to':now()})
                except PaymentError:continue
                h.db().execute("UPDATE order_payment_attempts SET status='cancelled',updated_at=? WHERE id=?",(now(),attempt['id']))

    def refund(store,order):
        sync(order,store)
        rows=h.rows("SELECT * FROM order_payment_transactions WHERE store_id=? AND order_id=? AND status='approved' AND refunded=0",(store['id'],order['id']))
        if len(rows)!=1 or rows[0]['amount']!=order['total']:raise PaymentError('Confira as cobranças no Mercado Pago antes de solicitar o estorno.')
        row=rows[0]
        key=row['refund_key'] or f"sca-refund-{store['id']}-{order['id']}-{row['provider_id']}"
        with h.transaction() as conn:
            current=conn.execute('SELECT * FROM order_payment_transactions WHERE id=?',(row['id'],)).fetchone()
            recent=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(timespec='seconds')
            if current['refund_state']=='processing' and current['refund_started_at']>recent:raise PaymentError('Estorno em conferência. Atualize o pagamento antes de tentar novamente.')
            if current['status']!='approved' or current['refunded']:raise PaymentError('Este pagamento já foi estornado ou alterado.')
            conn.execute("UPDATE order_payment_transactions SET refund_key=?,refund_state='processing',refund_started_at=? WHERE id=?",(key,now(),row['id']))
        try:
            attempt=h.one('SELECT * FROM order_payment_attempts WHERE id=?',(row['attempt_id'],))
            access=token(store,dict(attempt))
            mp().refund(access,row['provider_id'],key)
            info=mp().get_payment(access,row['provider_id'])
            reconcile(attempt,info,row['provider_id'])
        except Exception:
            # Same stable key remains retained; never automatically issue a new refund.
            h.db().execute("UPDATE order_payment_transactions SET refund_state='uncertain' WHERE id=?",(row['id'],))
            raise PaymentError('O estorno ficou em conferência. Atualize o pagamento; não repita por outro canal sem conferir.') from None
        h.db().execute("UPDATE order_payment_transactions SET refund_state='requested' WHERE id=?",(row['id'],))
        return state(order)

    app.extensions.update(online_create=create,online_sync=sync,online_webhook=webhook,online_state=state,
                          online_cancel=cancel_pending,online_refund=refund)
