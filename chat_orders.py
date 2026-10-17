"""Deterministic, opt-in WhatsApp ordering using the normal order pipeline."""
import json
import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from werkzeug.exceptions import HTTPException
from flask import request

from inbox_service import normalize, read_json, write_value, stamp, preferences, sending_since


def cart_key(sid, tid):
    return f'inbox.cart.{sid}.{tid}'


def forget_cart(conn, sid, tid):
    conn.execute('DELETE FROM platform_settings WHERE key=?', (cart_key(sid, tid),))


def save_cart(conn, sid, tid, cart):
    cart['expires'] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec='seconds')
    write_value(conn, cart_key(sid, tid), json.dumps(cart, ensure_ascii=False))


def cash(value):
    return ('R$ %.2f' % (value / 100)).replace('.', ',')


def groups(product):
    result = list(product.get('option_groups') or [])
    extras = product.get('extras') or []
    if extras:
        result.append({'name': 'Adicionais', 'min': 0, 'max': sum(o.get('max_quantity', 1) for o in extras), 'options': extras})
    return result


def payload(cart, thread):
    name=thread['name'].strip()
    return {'customer': name if len(name)>=2 else 'Cliente WhatsApp', 'phone': thread['phone'], 'mode': cart['mode'],
            'address': cart.get('address', ''), 'zone': cart.get('zone', ''), 'cep': cart.get('cep', ''),
            'payment': cart['payment'], 'change_for': cart.get('change_for'),
            'notes': cart.get('notes', ''), 'coupon': cart.get('coupon', ''),
            'items': cart['items'], 'marketing_consent': False}


def handle_chat(conn, app, store, thread, body, eid):
    """Called inside the webhook transaction; never creates an order or calls AI."""
    sid, tid = store['id'], thread['id']
    command = normalize(body)
    start = command in ('fazer pedido', 'quero pedir', 'novo pedido', 'pedido')
    if not preferences(conn, sid).get('chat_enabled', False):
        return None
    cart = read_json(conn, cart_key(sid, tid), {})
    if not start and not cart:
        return None
    if cart.get('stage') in ('submitted', 'processing'):
        return 'Sua confirmação já está sendo processada. Aguarde o número do pedido. Não precisa confirmar novamente.'
    if cart.get('stage') == 'done' and not start:
        return cart['receipt'] if command in ('confirmar', 'ajuda', 'pedido atual','cancelar') else None
    if cart.get('stage') in ('failed','paused') and not start:
        return cart.get('receipt','A montagem está pausada. Escreva FAZER PEDIDO para começar novamente ou ATENDENTE para ajuda.')
    if cart.get('expires', '') < stamp() and cart and not start:
        forget_cart(conn, sid, tid)
        return 'Seu pedido em montagem expirou. Escreva FAZER PEDIDO para começar de novo. Nenhum pedido foi criado por esta montagem.'
    if command == 'cancelar':
        forget_cart(conn, sid, tid)
        return 'Montagem cancelada. Escreva FAZER PEDIDO para começar novamente. Para cancelar um pedido já confirmado, fale com ATENDENTE.'
    from app import store_status
    if not store['enabled'] or not store_status(store)[0]:
        forget_cart(conn, sid, tid)
        return 'A loja não está recebendo pedidos agora. Confira os horários no cardápio ou escreva ATENDENTE.'
    catalog = app.extensions['chat_catalog'](store['slug'])
    products = {p['id']: p for p in catalog['products'] if p['stock'] != 0}
    public = catalog['store']
    if start:
        cart = {'stage': 'catalog', 'items': [], 'key': 'chat_' + secrets.token_hex(20), 'base':app.config['PUBLIC_URL'] or request.host_url.rstrip('/')}
    stage = cart['stage']
    if command == 'voltar':
        cart['stage'] = 'basket' if cart['items'] else 'catalog'
        cart.pop('pending', None)
        stage = cart['stage']
        command = 'ajuda'
    hint = '\n\nAJUDA: ver etapa · VOLTAR: sacola · CANCELAR: desistir · ATENDENTE: chamar equipe'

    def save(reply):
        save_cart(conn, sid, tid, cart)
        return reply[:3700] + hint

    def list_products(term=''):
        candidates = [p for p in products.values() if all(w in normalize(p['name']+' '+p['description']) for w in normalize(term).split())]
        offset = cart.get('offset', 0)
        selected = candidates[offset:offset+8]
        cart['choices'] = [p['id'] for p in selected]
        cart['more'] = offset+8 < len(candidates)
        cart['term'] = term
        lines = [f"{i+1}. {p['name']} — a partir de {cash(p['price'])}" for i,p in enumerate(selected)]
        return ('Escolha pelo número:\n'+'\n'.join(lines) if lines else 'Nenhum produto disponível para esta busca.') + '\nEscreva BUSCAR e o nome para pesquisar.' + ('\nMAIS: próxima página.' if cart['more'] else '')

    def basket():
        lines = [f"{i+1}. {line['quantity']}× {products.get(line['product_id'], {}).get('name', 'Produto alterado')}" for i,line in enumerate(cart['items'])]
        return 'Sua sacola:\n'+'\n'.join(lines)+'\n\n1: adicionar outro produto\n2: finalizar\nREMOVER e o número do item: retirar da sacola\nCUPOM e o código: aplicar ao finalizar'

    def choose_group():
        product = products.get(cart['pending']['product_id'])
        if not product:
            cart['stage'] = 'catalog';cart.pop('pending', None)
            return 'O produto não está mais disponível. '+list_products()
        options_groups = groups(product)
        pos = cart['pending'].get('group', 0)
        if pos >= len(options_groups):
            cart['stage'] = 'quantity'
            return 'Quantas unidades? Responda com um número de 1 a 50.'
        group = options_groups[pos]
        available = [o for o in group['options'] if o.get('available') is not False]
        if sum(o.get('max_quantity',1) for o in available)<group['min']:
            cart['stage']='catalog';cart.pop('pending',None)
            return 'Este produto está sem opções obrigatórias disponíveis. Escolha outro produto ou escreva ATENDENTE.\n'+list_products()
        if len(available) > 30:
            cart['stage'] = 'catalog';cart.pop('pending', None)
            return 'Este produto tem muitas opções. Monte pelo cardápio ou escreva ATENDENTE.'
        cart['pending']['choices'] = [o['id'] for o in available]
        lines = [f"{i+1}. {o['name']} (+{cash(o['price'])})" for i,o in enumerate(available)]
        return f"{group['name']}: escolha de {group['min']} a {group['max']}.\n"+'\n'.join(lines)+'\nResponda com números separados por vírgula. Repita um número se a opção permitir quantidade.'+ ('\n0: sem estas opções.' if not group['min'] else '')

    if command=='ajuda' and stage not in ('catalog','basket','options','review'):
        prompts={'quantity':'Informe uma quantidade de 1 a 50.','item_notes':'Escreva uma observação do item ou 0 para continuar.',
                 'mode':'1. Entrega\n2. Retirada na loja','cep':'Informe o CEP com oito dígitos.',
                 'address':'Informe rua, número, bairro e complemento.','notes':'Escreva uma observação do pedido ou 0 para continuar.',
                 'change':'Informe o valor para troco, como 100,00, ou 0 se não precisar.'}
        if stage=='zone':return save('Escolha o bairro:\n'+'\n'.join(f'{i+1}. {name}' for i,name in enumerate(cart['zones'])))
        if stage=='payment':return save('Escolha o pagamento:\n'+'\n'.join(f'{i+1}. '+{'pix':'Pix manual','pix_online':'Pix online','card':'Cartão na entrega/retirada','cash':'Dinheiro'}[name] for i,name in enumerate(cart['payments'])))
        return save(prompts.get(stage,'Escreva VOLTAR para rever a sacola.'))

    if stage == 'catalog':
        if start or command == 'ajuda':
            return save(list_products(cart.get('term', '')))
        if command == 'mais':
            cart['offset'] = cart.get('offset', 0)+8 if cart.get('more') else 0
            return save(list_products(cart.get('term', '')))
        if command.startswith('buscar '):
            cart['offset'] = 0
            return save(list_products(body.strip()[7:].strip()[:80]))
        if not command.isdigit() or not 1 <= int(command) <= len(cart.get('choices', [])):
            return save('Responda com o número de um produto, ou BUSCAR e o nome.')
        pid = cart['choices'][int(command)-1]
        if pid not in products:
            return save('Este produto saiu do cardápio. '+list_products())
        cart['pending'] = {'product_id': pid, 'option_ids': [], 'group': 0}
        cart['stage'] = 'options'
        return save(products[pid]['name']+'\n'+choose_group())
    if stage == 'options':
        if command == 'ajuda':return save(choose_group())
        product = products.get(cart['pending']['product_id'])
        if not product:return save(choose_group())
        group = groups(product)[cart['pending']['group']]
        options = {o['id']: o for o in group['options'] if o.get('available') is not False}
        if not re.fullmatch(r'\d+(?:\s*,\s*\d+)*', body.strip()):return save('Use somente os números das opções, separados por vírgula.')
        numbers = [int(n) for n in body.split(',')]
        if numbers == [0] and not group['min']:numbers = []
        choices = cart['pending'].get('choices', [])
        if not group['min'] <= len(numbers) <= group['max'] or any(not 1 <= n <= len(choices) for n in numbers):return save('Quantidade ou opção inválida. '+choose_group())
        ids = [choices[n-1] for n in numbers]
        if any(i not in options or ids.count(i)>options[i].get('max_quantity',1) for i in ids):return save('Esta opção não permite essa quantidade ou mudou. '+choose_group())
        cart['pending']['option_ids'].extend(ids);cart['pending']['group'] += 1
        return save(choose_group())
    if stage == 'quantity':
        if not command.isdigit() or not 1 <= int(command) <= 50:return save('Informe a quantidade de 1 a 50.')
        cart['pending']['quantity'] = int(command);cart['stage'] = 'item_notes'
        return save('Alguma observação para este item? Escreva a observação ou 0 para continuar sem observação.')
    if stage == 'item_notes':
        line = cart.pop('pending');line = {k:line[k] for k in ('product_id','option_ids','quantity')}
        line['notes'] = '' if command == '0' else body.strip()[:200]
        cart['items'].append(line);cart['stage'] = 'basket'
        return save(basket())
    if stage == 'basket':
        if command == 'ajuda':return save(basket())
        if command.startswith('remover '):
            selected = command.split()[-1]
            if selected.isdigit() and 1 <= int(selected) <= len(cart['items']):cart['items'].pop(int(selected)-1)
            return save(basket())
        if command.startswith('cupom '):
            code = body.strip()[6:].strip()[:30].upper()
            cart['coupon'] = '' if code=='0' else code
            return save('Cupom '+('removido.' if not cart['coupon'] else 'anotado. O servidor confere a validade no resumo. Para remover, escreva CUPOM 0.')+'\n'+basket())
        if command == '1':
            if len(cart['items']) >= 20:return save('Limite de 20 itens diferentes nesta conversa. Finalize a sacola ou remova um item.')
            cart['stage'] = 'catalog';cart['offset'] = 0
            return save(list_products())
        if command != '2' or not cart['items']:return save('Adicione um produto antes de finalizar.\n'+basket())
        cart['stage'] = 'mode'
        return save('Como quer receber?\n1. Entrega\n2. Retirada na loja')
    if stage == 'mode':
        if command not in ('1','2'):return save('Escolha 1 para entrega ou 2 para retirada.')
        cart['mode'] = 'delivery' if command == '1' else 'pickup'
        if command == '2':cart['stage'] = 'notes';return save('Observação do pedido? Escreva 0 se não tiver.')
        zones = public.get('delivery_zones') or []
        if public.get('postal_zones'):
            cart['stage'] = 'cep'
            return save('Qual o CEP da entrega? Informe os oito dígitos.')
        if zones:
            cart['stage'] = 'zone';cart['zones'] = [z['name'] for z in zones]
            return save('Escolha o bairro pelo número:\n'+'\n'.join(f"{i+1}. {z['name']}" for i,z in enumerate(zones)))
        cart['stage'] = 'address';return save('Informe o endereço completo: rua, número, bairro e complemento.')
    if stage == 'cep':
        cep = re.sub(r'\D','',body)
        if len(cep)!=8:return save('Informe um CEP com oito dígitos.')
        cart['cep'] = cep;cart['stage'] = 'address'
        return save('Informe o endereço completo: rua, número, bairro e complemento.')
    if stage == 'zone':
        if not command.isdigit() or not 1<=int(command)<=len(cart['zones']):return save('Escolha o número do bairro listado ou VOLTAR para rever a sacola.')
        cart['zone'] = cart['zones'][int(command)-1];cart['stage'] = 'address'
        return save('Informe o endereço completo: rua, número, bairro e complemento.')
    if stage == 'address':
        if not 8<=len(body.strip())<=400:return save('Confira o endereço completo, com 8 a 400 caracteres.')
        cart['address'] = body.strip();cart['stage'] = 'notes'
        return save('Observação do pedido? Escreva 0 se não tiver.')
    if stage == 'notes':
        cart['notes'] = '' if command=='0' else body.strip()[:500]
        cart['payments'] = [p for p in public['payments'] if p in ('cash','card','pix') or (p=='pix_online' and public.get('mp_connected'))]
        if not cart['payments']:return save('Nenhuma forma de pagamento está disponível. Escreva ATENDENTE.')
        cart['stage'] = 'payment'
        names = {'cash':'Dinheiro','card':'Cartão na entrega/retirada','pix':'Pix com confirmação pela loja','pix_online':'Pix online'}
        return save('Como vai pagar?\n'+'\n'.join(f"{i+1}. {names[p]}" for i,p in enumerate(cart['payments'])))
    if stage == 'payment':
        if not command.isdigit() or not 1<=int(command)<=len(cart['payments']):return save('Escolha o número de uma forma de pagamento listada.')
        cart['payment'] = cart['payments'][int(command)-1]
        if cart['payment']=='cash':cart['stage']='change';return save('Troco para quanto? Informe o valor em reais ou 0 se não precisar de troco.')
        cart['stage'] = 'review'
    elif stage == 'change':
        if not re.fullmatch(r'\d{1,6}(?:[,.]\d{1,2})?',body.strip()):return save('Informe um valor, como 100,00, ou 0 para não precisar de troco.')
        value = round(float(body.replace(',','.'))*100)
        cart['change_for'] = value or None;cart['stage'] = 'review'
    elif stage == 'review':
        if command == 'confirmar':
            cart['stage'] = 'submitted';cart['submitted_at'] = stamp();save_cart(conn,sid,tid,cart)
            return 'Confirmação recebida. Estamos validando preço, estoque e entrega. Aguarde o número do pedido antes de pagar. Não precisa confirmar novamente.'
        if command not in ('ajuda','resumo'):return save('Escreva CONFIRMAR para concluir, VOLTAR para rever a sacola ou CANCELAR para desistir.')
    try:
        value = payload(cart,thread)
        quote = app.extensions['chat_quote'](store['slug'],value)
        if cart.get('change_for') and cart['change_for']<quote['total']:raise ValueError('O troco deve cobrir o total.')
        lines=[]
        for line in cart['items']:
            product=products[line['product_id']]
            options={o['id']:g['name']+': '+o['name'] for g in groups(product) for o in g['options']}
            lines.append(f"{line['quantity']}× {product['name']}")
            if line['option_ids']:lines.append('Opções: '+', '.join(f"{line['option_ids'].count(oid)}× {options[oid]}" for oid in dict.fromkeys(line['option_ids'])))
            if line['notes']:lines.append('Obs. do item: '+line['notes'])
        payment={'pix':'Pix com confirmação pela loja','pix_online':'Pix online','card':'Cartão na entrega/retirada','cash':'Dinheiro'}[cart['payment']]
        summary='Confira antes de confirmar:\n'+'\n'.join(lines)+f"\nProdutos: {cash(quote['subtotal'])}\nDescontos: {cash(quote['discount'])}\nEntrega: {cash(quote['delivery_fee'])}\nTOTAL: {cash(quote['total'])}\nPagamento: {payment}\n"+('Retirada na loja' if cart['mode']=='pickup' else 'Entrega: '+cart.get('address','')+(' · CEP '+cart['cep'] if cart.get('cep') else ''))
        if cart.get('change_for'):summary+='\nTroco para: '+cash(cart['change_for'])
        if cart.get('notes'):summary+='\nObs. do pedido: '+cart['notes']
        summary+='\n\nEscreva CONFIRMAR para criar o pedido. Nada foi cobrado.'
        if len(summary)>3700:
            cart['stage']='basket'
            return save('Este pedido tem muitos detalhes para um resumo no chat. Remova itens ou finalize pelo cardápio/ATENDENTE.\n'+basket())
        cart['expected_total'] = quote['total']
        cart['payload'] = {**value,'expected_total':quote['total']}
        return save(summary)
    except (HTTPException,ValueError) as exc:
        cart['stage'] = 'basket'
        return save('Não foi possível finalizar: '+getattr(exc,'description',str(exc))+'\nCorrija pelo menu da sacola ou escreva ATENDENTE.\n'+basket())


def process_chat_orders(app, limit=2, stop_event=None):
    """Claim durable confirmations, then use the standard transactional order service."""
    from database import connect
    conn = connect(app.config)
    processed = 0
    try:
        if time.monotonic()>=app.extensions.get('chat_cleanup_after',0):
            app.extensions['chat_cleanup_after']=time.monotonic()+300
            for row in conn.execute("SELECT key,value FROM platform_settings WHERE key LIKE 'inbox.cart.%'"):
                cart=json.loads(row['value'])
                if cart.get('stage') not in ('submitted','processing') and cart.get('expires','')<stamp():conn.execute('DELETE FROM platform_settings WHERE key=?',(row['key'],))
        pending_query="SELECT key,value FROM platform_settings WHERE key LIKE 'inbox.cart.%' AND (value LIKE ? OR value LIKE ?)"
        pending_values=('%"stage": "submitted"%','%"stage": "processing"%')
        if not conn.execute(pending_query+' LIMIT 1',pending_values).fetchone():return 0
        for _ in range(limit):
            if stop_event is not None and stop_event.is_set():break
            conn.execute('BEGIN IMMEDIATE')
            try:
                selected = None
                for row in conn.execute(pending_query,pending_values):
                    cart = json.loads(row['value'])
                    if cart.get('stage') == 'processing' and cart.get('claimed_at','') < (datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec='seconds'):
                        cart['stage'] = 'submitted'
                    if cart.get('stage') != 'submitted':continue
                    _,_,sid,tid = row['key'].split('.')
                    store = conn.execute('SELECT * FROM stores WHERE id=?',(int(sid),)).fetchone()
                    thread = conn.execute('SELECT * FROM inbox_threads WHERE id=? AND store_id=?',(int(tid),int(sid))).fetchone()
                    if not store or not thread or thread['assigned_to'] or thread['state']!='open' or not store['inbox_bot'] or not sending_since(conn,int(sid)) or not preferences(conn,int(sid)).get('chat_enabled'):
                        cart['stage']='paused';save_cart(conn,int(sid),int(tid),cart);continue
                    cart['stage']='processing';cart['claimed_at']=stamp();save_cart(conn,int(sid),int(tid),cart)
                    selected=(int(sid),int(tid),store['slug'],cart);break
                conn.execute('COMMIT')
            except Exception:conn.execute('ROLLBACK');raise
            if not selected:break
            sid,tid,slug,cart = selected
            try:
                with app.test_request_context('/_chat-order',method='POST',json=cart['payload']):
                    response,code = app.extensions['chat_place_order'](slug,cart['payload'],cart['key'],source='whatsapp',chat_thread_id=tid)
                    result = response.get_json()
                receipt = f"Pedido #{result['number']} criado! Total: {cash(result['total'])}. Acompanhe: {cart.get('base',app.config['PUBLIC_URL'])}/pedido/{result['token']}\nO pagamento segue a forma escolhida. Para alterações ou cancelamento, escreva ATENDENTE."
                outcome = {'stage':'done','receipt':receipt}
            except HTTPException as exc:
                digest=hashlib.sha256(json.dumps(cart['payload'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
                existing=conn.execute('SELECT number,total,tracking_token FROM orders WHERE store_id=? AND idempotency_key=? AND payload_hash=?',(sid,cart['key'],digest)).fetchone()
                if existing:
                    receipt=f"Pedido #{existing['number']} criado! Total: {cash(existing['total'])}. Acompanhe: {cart.get('base',app.config['PUBLIC_URL'])}/pedido/{existing['tracking_token']}\nPara alterações ou cancelamento, escreva ATENDENTE."
                    outcome={'stage':'done','receipt':receipt}
                else:
                    receipt = 'Seu pedido ainda não foi criado: '+exc.description+'\nEscreva FAZER PEDIDO para montar novamente com os dados atuais ou ATENDENTE para ajuda.'
                    outcome = {'stage':'failed','receipt':receipt}
            except Exception:
                # The commit may already exist: retain the exact key/payload for safe recovery.
                app.logger.error('Falha ao finalizar pedido guiado; confirmação preservada para recuperação.')
                continue
            conn.execute('BEGIN IMMEDIATE')
            try:
                if conn.execute('SELECT id FROM inbox_threads WHERE id=? AND store_id=?',(tid,sid)).fetchone():
                    save_cart(conn,sid,tid,outcome)
                    conn.execute("INSERT INTO inbox_messages(store_id,thread_id,direction,body,external_id,status,automated,created_at) VALUES(?,?,'out',?,?,'queued',?,?) ON CONFLICT(store_id,external_id) DO NOTHING",(sid,tid,receipt,'chat-result:'+cart['key'],2 if outcome['stage']=='done' else 1,stamp()))
                    conn.execute('UPDATE inbox_threads SET updated_at=? WHERE id=?',(stamp(),tid))
                conn.execute('COMMIT');processed+=1
            except Exception:conn.execute('ROLLBACK');raise
    finally:conn.close()
    return processed
