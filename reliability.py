"""Tenant setup, receivables and actionable operational diagnostics."""
import json
import secrets
import time
import click
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from flask import abort, g, jsonify, request, session

from account_recovery import mail_ready
from inbox_service import delivery_health, read_json, write_value


def register_reliability(app, helpers):
    h = SimpleNamespace(**helpers)
    timings = deque(maxlen=1000)

    @app.before_request
    def begin_observation():
        g.operation_started = time.monotonic()
        g.operation_request_id = secrets.token_hex(8)

    @app.after_request
    def observe_response(response):
        elapsed = round((time.monotonic()-getattr(g, 'operation_started', time.monotonic()))*1000)
        timings.append((elapsed, response.status_code))
        response.headers['X-Request-ID'] = getattr(g, 'operation_request_id', '')
        if elapsed >= 2000 or response.status_code >= 500:
            app.logger.warning('operation_request endpoint=%s status=%s duration_ms=%s request_id=%s',
                request.endpoint or 'unknown', response.status_code, elapsed, response.headers['X-Request-ID'])
        return response

    def setup_state():
        store, sid = g.store, g.store['id']
        checked = read_json(h.db(), 'setup.'+str(sid), {})
        products = h.one('SELECT COUNT(*) AS n FROM products WHERE store_id=? AND active=1', (sid,))['n']
        payments = json.loads(store['payments'])
        usable = any(p in ('cash','card') or p == 'pix' and store['pix_key'] or
            p in ('pix_online','card_online') and store['mp_token'] for p in payments)
        items = [
            dict(id='products', title='Cadastre seu primeiro produto', detail='Inclua nome, preço, foto e escolhas do cliente.', tab='products', done=products>0),
            dict(id='contact', title='Confira endereço e WhatsApp', detail='É assim que o cliente encontra e fala com a loja.', tab='settings', done=bool(store['address'] and store['phone'])),
            dict(id='hours', title='Defina como a loja abre e fecha', detail='Use horários automáticos ou confirme que vai abrir e fechar manualmente.', tab='settings', done=bool(store['auto_hours'] and json.loads(store['hours']) or checked.get('hours'))),
            dict(id='delivery', title='Confira entrega e retirada', detail='Revise taxas, bairros, pedido mínimo e prazo antes de vender.', tab='settings', done=bool(checked.get('delivery'))),
            dict(id='payments', title='Escolha os pagamentos', detail='Pix e cartão online precisam da conta Mercado Pago da própria loja.', tab='settings', done=bool(usable)),
            dict(id='printing', title='Teste a impressora deste caixa', detail='Imprima um exemplo e confira o papel no equipamento.', tab='printing', done=bool(checked.get('printing'))),
            dict(id='menu', title='Confira o pedido antes de abrir', detail='Faça uma simulação no PDV, sem confirmar venda, e confira seu cardápio no celular.', tab='pos', done=bool(checked.get('menu'))),
        ]
        return dict(store_id=sid, has_orders=bool(h.one('SELECT id FROM orders WHERE store_id=? LIMIT 1',(sid,))),
                    items=items, completed=sum(x['done'] for x in items), total=len(items),
                    note='Confirmações de entrega, impressão e conferência são declarações da equipe, não validações automáticas de hardware ou pagamento.')

    @app.get('/api/admin/setup')
    @h.owner
    def merchant_setup():
        return jsonify(setup_state())

    @app.post('/api/admin/setup/check')
    @h.owner
    def merchant_setup_check():
        value = h.data()
        item = h.text(value, 'item', 1, 30)
        if item not in ('hours','delivery','printing','menu') or type(value.get('checked')) is not bool:
            abort(400, description='Etapa de configuração inválida.')
        with h.transaction() as conn:
            key = 'setup.'+str(g.store['id'])
            saved = read_json(conn, key, {})
            if value['checked']:
                saved[item] = {'at': h.now(), 'user_id': g.user['id']}
            else:
                saved.pop(item, None)
            write_value(conn, key, json.dumps(saved))
        return jsonify(setup_state())

    @app.get('/api/admin/print-orders/<int:oid>')
    @h.owner
    def print_order(oid):
        return jsonify(order=h.order_dict(h.owned('orders', oid)))

    def diagnostics(sid=None):
        start = time.monotonic()
        h.one('SELECT 1')
        conditions, params = (' AND store_id=?', [sid]) if sid is not None else ('', [])
        since = (datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(timespec='seconds')
        counts = {}
        for key, table, where in [
            ('messages_waiting','inbox_messages',"direction='out' AND status='queued' AND created_at<?"),
            ('messages_uncertain','inbox_messages',"direction='out' AND status IN ('uncertain','held')"),
            ('payments_uncertain','order_payment_attempts',"status IN ('uncertain','review') OR (status='creating' AND updated_at<?)"),
            ('refunds_uncertain','order_payment_transactions',"refund_state='uncertain' OR (refund_state='processing' AND refund_started_at<?)"),
            ('campaigns_waiting','marketing_jobs',"status='queued' AND due_at<?"),
        ]:
            counts[key] = h.one(f'SELECT COUNT(*) AS n FROM {table} WHERE ({where})'+conditions,
                ([since] if '?' in where else [])+params)['n']
        dispatcher = delivery_health(app, h.db())
        alerts = []
        if counts['payments_uncertain'] or counts['refunds_uncertain']:
            alerts.append(dict(code='payments', title='Pagamentos para conferir', detail='Confira as tentativas e estornos no Mercado Pago antes de cobrar novamente.', tab='receivables'))
        if counts['messages_uncertain']:
            alerts.append(dict(code='messages', title='Mensagens aguardam conferência', detail='Veja no atendimento se a mensagem chegou antes de reenviar.', tab='inbox'))
        if counts['messages_waiting']:
            alerts.append(dict(code='queue', title='Fila de atendimento com atraso', detail='Confira conexão do WhatsApp e processamento das mensagens.', tab='inbox'))
        if counts['messages_waiting'] and (not dispatcher['running'] or dispatcher['last_error']):
            alerts.append(dict(code='dispatcher', title='Processamento precisa de atenção', detail='O serviço de atendimento não apresentou atividade recente sem erro.', tab='inbox'))
        if counts['campaigns_waiting']:
            alerts.append(dict(code='campaigns', title='Campanhas aguardando envio', detail='Confira a fila de marketing e a conexão do WhatsApp.', tab='marketing'))
        result = dict(at=h.now(), database_ms=round((time.monotonic()-start)*1000), counts=counts, alerts=alerts)
        if sid is None:
            observed = list(timings)
            samples = sorted(x[0] for x in observed)
            mail_error = h.one("SELECT value FROM platform_settings WHERE key='recovery.delivery_error'")
            result.update(mail_ready=mail_ready(app), mail_delivery_error=bool(mail_error and mail_error['value']),
                dispatcher=dispatcher, process_sample=dict(requests=len(samples), errors=sum(x[1]>=500 for x in observed),
                    p95_ms=samples[min(len(samples)-1, int(len(samples)*.95))] if samples else None),
                recovery_drill=read_json(h.db(), 'operations.restore_drill'),
                limits='Métricas de requisição são uma amostra deste processo; não substituem o monitoramento externo.')
        return result

    @app.get('/api/admin/operations/health')
    @h.owner
    def merchant_operational_health():
        return jsonify(diagnostics(g.store['id']))

    @app.get('/api/platform/operations/health')
    def platform_operational_health():
        user = h.one('SELECT id,auth_version,platform_admin FROM users WHERE id=?', (session.get('uid',-1),))
        if not user or user['auth_version'] != session.get('version'):
            abort(401, description='Entre na sua conta.')
        if not user['platform_admin']:
            abort(403, description='Esta área é exclusiva do dono da plataforma.')
        return jsonify(diagnostics())

    @app.get('/api/admin/receivables')
    @h.owner
    def merchant_receivables():
        days = request.args.get('days','30')
        if days not in ('1','7','30','90','365'):
            abort(400, description='Período inválido.')
        start = (datetime.now(timezone.utc)-timedelta(days=int(days))).isoformat(timespec='seconds')
        sid = g.store['id']
        transactions = h.rows('''SELECT t.id,t.order_id,o.number,t.kind,t.amount,t.refunded,t.fee,t.net_amount,t.status,
            t.approved_at,t.updated_at,t.release_at,t.release_status,t.refund_state
            FROM order_payment_transactions t JOIN orders o ON o.id=t.order_id AND o.store_id=t.store_id
            WHERE t.store_id=? AND t.updated_at>=? ORDER BY t.id DESC LIMIT 501''', (sid,start))
        totals = dict(h.one('''SELECT COUNT(*) AS transactions,
            COALESCE(SUM(CASE WHEN status IN ('approved','refunded','charged_back','in_mediation') THEN amount ELSE 0 END),0) AS gross,
            COALESCE(SUM(refunded),0) AS refunded,
            COALESCE(SUM(CASE WHEN status IN ('approved','refunded','charged_back','in_mediation') THEN fee ELSE 0 END),0) AS fees,
            COALESCE(SUM(CASE WHEN status='approved' AND refunded=0 AND net_amount IS NOT NULL AND release_status='released' THEN net_amount ELSE 0 END),0) AS released,
            COALESCE(SUM(CASE WHEN status='approved' AND refunded=0 AND net_amount IS NOT NULL AND release_status='pending' THEN net_amount ELSE 0 END),0) AS pending,
            COALESCE(SUM(CASE WHEN status='approved' AND (net_amount IS NULL OR release_status NOT IN ('released','pending') OR refunded>0) THEN 1 ELSE 0 END),0) AS unknown
            FROM order_payment_transactions WHERE store_id=? AND updated_at>=?''', (sid,start)))
        attempts = h.rows("SELECT a.id,a.order_id,o.number,a.kind,a.status,a.amount,a.updated_at FROM order_payment_attempts a JOIN orders o ON o.id=a.order_id AND o.store_id=a.store_id WHERE a.store_id=? AND a.status IN ('creating','uncertain','review','authorized','in_process','in_mediation') ORDER BY a.id DESC LIMIT 100", (sid,))
        return jsonify(transactions=transactions[:500], truncated=len(transactions)>500, totals=totals, attempts=attempts,
            connected=bool(g.store['mp_token']), at=h.now(),
            note='Dados da última conferência com o Mercado Pago. Liberado significa disponível na conta do provedor, não transferência para o banco. Estornos parciais e dados não informados exigem conferência. O período considera a última atualização da transação.')

    app.extensions['operational_diagnostics'] = diagnostics

    @app.cli.command('operations-check')
    def operations_check():
        """Read-only diagnostics for the operator or an external monitoring job."""
        result = diagnostics()
        click.echo(json.dumps(result, ensure_ascii=False))
        if result['alerts']:
            raise click.exceptions.Exit(1)
