"""Tenant-scoped inbox preferences and an opt-in, durable delivery loop."""
import json
import re
import threading
import unicodedata
from datetime import datetime, timezone

VARIABLES = {'nome', 'loja', 'link', 'horario', 'pix', 'entrega', 'minimo'}
DEFAULTS = {
    'closed_enabled': True,
    'closed_message': 'Olá, {nome}! A {loja} está fechada neste momento. {horario}. Confira o cardápio e os horários: {link}\nPara falar com a equipe, escreva ATENDENTE.',
    'rules': [
        {'id': 'menu', 'name': 'Cardápio e boas-vindas', 'keywords': ['menu', 'cardapio', 'oi', 'ola', 'bom dia', 'boa tarde', 'boa noite'], 'enabled': True, 'message': 'Olá, {nome}! Veja o cardápio da {loja}: {link}\nPara falar com a equipe, escreva ATENDENTE.'},
        {'id': 'hours', 'name': 'Horário de atendimento', 'keywords': ['horario', 'horarios', 'aberto', 'abre'], 'enabled': True, 'message': '{loja}: {horario}. Confira horários e agendamentos: {link}'},
        {'id': 'delivery', 'name': 'Entrega e pedido mínimo', 'keywords': ['entrega', 'frete', 'taxa', 'pedido minimo'], 'enabled': True, 'message': 'Na {loja}, a taxa padrão é {entrega} e o pedido mínimo em produtos é {minimo}. O valor final depende do endereço e aparece antes de confirmar: {link}'},
        {'id': 'pix', 'name': 'Pagamento por Pix', 'keywords': ['pix', 'pagamento'], 'enabled': True, 'message': 'As formas de pagamento disponíveis aparecem ao finalizar: {link}. Chave Pix cadastrada na loja: {pix}. Confira o valor do pedido com a equipe antes de transferir.'},
    ],
    'quick_replies': [
        {'shortcut': 'cardapio', 'name': 'Enviar cardápio', 'message': 'Olá, {nome}! Nosso cardápio está aqui: {link}'},
        {'shortcut': 'entrega', 'name': 'Informações de entrega', 'message': 'A taxa padrão é {entrega}. Confira a taxa do seu endereço ao finalizar: {link}'},
        {'shortcut': 'aguarde', 'name': 'Vou conferir', 'message': 'Só um instante, {nome}. Vou conferir essa informação para você.'},
    ],
}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def normalize(value):
    value = ''.join(c for c in unicodedata.normalize('NFD', value.casefold()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', value)).strip()


def read_json(conn, key, default=None):
    row = conn.execute('SELECT value FROM platform_settings WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else default
    except (ValueError, TypeError):
        return default


def write_value(conn, key, value):
    conn.execute('INSERT INTO platform_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))


def preferences(conn, sid):
    value = read_json(conn, 'inbox.config.' + str(sid))
    return value if isinstance(value, dict) else json.loads(json.dumps(DEFAULTS))


def sending_since(conn, sid):
    row = conn.execute('SELECT value FROM platform_settings WHERE key=?', ('inbox.sending.' + str(sid),)).fetchone()
    return row['value'] if row else ''


def validate_preferences(value):
    def text(v, low, high):
        if not isinstance(v, str) or not low <= len(v.strip()) <= high:
            raise ValueError('Confira os tamanhos dos textos e palavras-chave.')
        return v.strip()

    def message(v):
        v = text(v, 1, 1500)
        if any(key not in VARIABLES for key in re.findall(r'\{([^{}]*)\}', v)) or re.search(r'[{}]', re.sub(r'\{[^{}]*\}', '', v)):
            raise ValueError('Use somente as variáveis de mensagem exibidas na tela.')
        return v

    if not isinstance(value, dict) or type(value.get('closed_enabled')) is not bool:
        raise ValueError('Configuração de respostas inválida.')
    result = {'closed_enabled': value['closed_enabled'], 'closed_message': message(value.get('closed_message'))}
    for family, maximum in [('rules', 12), ('quick_replies', 20)]:
        entries = value.get(family)
        if not isinstance(entries, list) or len(entries) > maximum:
            raise ValueError('Limite de respostas excedido.')
        result[family] = []; seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Resposta inválida.')
            key_field = 'id' if family == 'rules' else 'shortcut'
            key = text(entry.get(key_field), 1, 40)
            if not re.fullmatch(r'[a-z0-9_-]+', key) or key in seen:
                raise ValueError('Use identificadores únicos, com letras minúsculas, números e hífen.')
            seen.add(key)
            item = {key_field: key, 'name': text(entry.get('name'), 1, 80), 'message': message(entry.get('message'))}
            if family == 'rules':
                words = entry.get('keywords')
                if not isinstance(words, list) or not 1 <= len(words) <= 10 or type(entry.get('enabled')) is not bool:
                    raise ValueError('Informe de 1 a 10 palavras-chave por resposta.')
                item['keywords'] = [normalize(text(w, 2, 50)) for w in words]
                if any(not w or re.search(r'\b(atendente|humano)\b', w) for w in item['keywords']):
                    raise ValueError('ATENDENTE e HUMANO são reservados ao atendimento da equipe.')
                item['enabled'] = entry['enabled']
            result[family].append(item)
    return result


def template_values(store, name, base):
    from app import store_status
    currency = lambda n: ('R$ %.2f' % ((n or 0) / 100)).replace('.', ',')
    return {'nome': name.split(' ')[0] if name else 'cliente', 'loja': store['name'], 'link': base + '/loja/' + store['slug'],
            'horario': store_status(store)[1], 'pix': store['pix_key'] or 'consulte a equipe',
            'entrega': currency(store['delivery_fee']), 'minimo': currency(store['minimum_order'])}


def render_message(template, values):
    return re.sub(r'\{([a-z]+)\}', lambda m: str(values.get(m[1], m[0])), template)[:4000]


def automatic_reply(settings, store, body, name, base):
    from app import store_status
    values = template_values(store, name, base)
    if settings['closed_enabled'] and not store_status(store)[0]:
        return render_message(settings['closed_message'], values)
    normalized = normalize(body)
    for rule in settings['rules']:
        if rule['enabled'] and any(re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', normalized) for word in rule['keywords']):
            return render_message(rule['message'], values)
    return ''


def delivery_health(app, conn):
    value = read_json(conn, 'inbox.dispatcher', {})
    recent = False
    try:
        recent = (datetime.now(timezone.utc) - datetime.fromisoformat(value['at'])).total_seconds() < 45
    except (KeyError, ValueError, TypeError):
        pass
    return {'mode': app.config.get('INBOX_DISPATCH_MODE', 'embedded'), 'running': recent, 'last_tick': value.get('at'),
            'last_error': bool(value.get('error')) if recent else False}


def delivery_tick(app, limit=5, stop_event=None):
    from database import connect
    from inbox import dispatch_inbox
    result = dispatch_inbox(app, limit, stop_event=stop_event)
    conn = connect(app.config)
    try:
        write_value(conn, 'inbox.dispatcher', json.dumps({'at': stamp(), 'error': False}))
    finally:
        conn.close()
    return result


def install_dispatcher(app):
    """Embedded mode shares the web service. Stores opt in; no historical queue is swept."""
    lock = threading.Lock()
    stopped = threading.Event()
    app.extensions['inbox_dispatch_stop'] = stopped

    def loop():
        while not stopped.is_set():
            try:
                delivery_tick(app, stop_event=stopped)
            except Exception:
                # Do not log provider payloads, contacts or credentials.
                app.logger.error('Falha ao processar a fila de atendimento.')
            stopped.wait(3)

    @app.before_request
    def ensure_dispatcher():
        if app.testing or app.config.get('INBOX_DISPATCH_MODE') != 'embedded':
            return
        with lock:
            thread = app.extensions.get('inbox_dispatch_thread')
            if thread and thread.is_alive():
                return
            thread = threading.Thread(target=loop, daemon=True, name='inbox-delivery')
            app.extensions['inbox_dispatch_thread'] = thread
            thread.start()
