"""Fiado autorizado pela loja, com limite transacional e recebimento pelo Caixa."""
from datetime import timedelta
from types import SimpleNamespace

from flask import abort,g,jsonify

from marketing import validate_phone,phone_key
from merchandising import local_time

DDL="""
CREATE TABLE IF NOT EXISTS credit_accounts (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), phone TEXT NOT NULL, name TEXT NOT NULL,
 credit_limit INTEGER NOT NULL CHECK(credit_limit>=0), due_days INTEGER NOT NULL DEFAULT 30, active INTEGER NOT NULL DEFAULT 1,
 UNIQUE(store_id,phone)
);
CREATE INDEX IF NOT EXISTS ix_credit_store ON credit_accounts(store_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_obligation_order ON obligations(order_id) WHERE order_id IS NOT NULL;
"""


def credit_debt(conn,sid,phone):
    return conn.execute('''SELECT COALESCE(SUM(b.amount-b.settled),0) FROM obligations b JOIN orders o ON o.id=b.order_id
        WHERE b.store_id=? AND b.voided_at IS NULL AND o.status!='cancelled' AND o.phone=?''',(sid,phone)).fetchone()[0]


def register_credit(app,helpers):
    h=SimpleNamespace(**helpers)

    @app.get('/api/admin/credit')
    @h.owner
    def credit_list():
        accounts=h.rows('SELECT * FROM credit_accounts WHERE store_id=? ORDER BY name',(g.store['id'],))
        for account in accounts:
            account['debt']=credit_debt(h.db(),g.store['id'],account['phone'])
            account['available']=max(0,account['credit_limit']-account['debt']) if account['active'] else 0
        return jsonify(accounts=accounts)

    @app.post('/api/admin/credit')
    @h.owner
    def credit_save():
        value=h.data();phone=validate_phone(value.get('phone'))
        with h.transaction() as conn:
            credit_limit=h.integer(value,'credit_limit',maximum=10**9)
            debt=credit_debt(conn,g.store['id'],phone)
            if credit_limit<debt:abort(409,description='O limite não pode ser menor que o saldo de fiado ainda em aberto.')
            conn.execute('''INSERT INTO credit_accounts(store_id,phone,name,credit_limit,due_days,active) VALUES(?,?,?,?,?,?)
                ON CONFLICT(store_id,phone) DO UPDATE SET name=excluded.name,credit_limit=excluded.credit_limit,due_days=excluded.due_days,active=excluded.active''',
                (g.store['id'],phone,h.text(value,'name',2,100),credit_limit,h.integer(value,'due_days',default=30,minimum=1,maximum=90),h.boolean(value,'active',True)))
        return jsonify(ok=True)

    def validate(conn,store,value,total):
        if value.get('payment')!='credit':return
        if not getattr(g,'manual_order',False):abort(403,description='Fiado só pode ser lançado pelo atendimento da loja.')
        phone=validate_phone(value.get('phone'))
        account=conn.execute('SELECT * FROM credit_accounts WHERE store_id=? AND phone=? AND active=1',(store['id'],phone)).fetchone()
        if not account or total>account['credit_limit']-credit_debt(conn,store['id'],phone):
            abort(409,description='Cliente sem fiado autorizado ou limite disponível insuficiente.')

    def attach(conn,store,oid,value,total):
        if value.get('payment')!='credit':return
        phone=phone_key(value['phone'])
        account=conn.execute('SELECT * FROM credit_accounts WHERE store_id=? AND phone=?',(store['id'],phone)).fetchone()
        conn.execute('UPDATE orders SET phone=? WHERE id=?',(phone,oid))
        if total:
            number=conn.execute('SELECT number FROM orders WHERE id=?',(oid,)).fetchone()[0]
            conn.execute("INSERT INTO obligations(store_id,description,kind,amount,due_on,created_at,order_id) VALUES(?,?,'receivable',?,?,?,?)",(store['id'],'Fiado #'+str(number)+' • '+account['name'],total,(local_time(store).date()+timedelta(days=account['due_days'])).isoformat(),h.now(),oid))

    def payment(conn,oid,net):
        conn.execute('UPDATE obligations SET settled=? WHERE order_id=?',(net,oid))

    def cancel(conn,oid):
        conn.execute('UPDATE obligations SET voided_at=? WHERE order_id=?',(h.now(),oid))

    app.extensions.update(credit_validate=validate,credit_attach=attach,credit_payment=payment,credit_cancel=cancel)
