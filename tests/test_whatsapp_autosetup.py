"""Ao ler o QR Code, o robô liga sozinho: recebe, responde e manda o cardápio sem a loja apertar mais nada."""
from inbox import dispatch_inbox
from tests.test_api import app, shop, send
from tests.test_growth import sql
from tests.test_inbox import InboxProvider, event


def linked(client):
    fake = InboxProvider()
    client.application.extensions['evolution'] = fake
    sql(client, "UPDATE stores SET wa_instance='test-instance' WHERE id=1")
    return fake


def hook(client, fake, text, **keys):
    return client.post('/webhooks/inbox/1', json=event(text, **keys), headers={'X-Webhook-Token': fake.token})


def test_connected_whatsapp_turns_the_robot_on_by_itself(shop):
    c, _ = shop
    fake = linked(c)
    status = c.get('/api/admin/whatsapp/status').json
    assert status == {'connected': True, 'activated': True}
    inbox = c.get('/api/admin/inbox').json
    assert inbox['configured'] and inbox['sending'] and inbox['bot']
    assert c.get('/api/admin/connectors').json['whatsapp']['enabled']
    assert hook(c, fake, 'oi').status_code == 200
    assert dispatch_inbox(c.application)['sent'] == 1
    assert '/loja/minha-loja' in fake.calls[-1][2]
    # Só na primeira vez: o que a loja desligar depois continua desligado.
    assert send(c, 'PUT', '/api/admin/inbox/bot', {'enabled': False}).status_code == 200
    assert c.get('/api/admin/whatsapp/status').json['activated'] is False
    assert c.get('/api/admin/inbox/connection').json['activated'] is False
    assert c.get('/api/admin/inbox').json['bot'] is False


def test_inbox_page_also_activates_and_disconnected_number_does_not(shop):
    c, _ = shop
    fake = linked(c)
    fake.state = lambda instance: (200, {'instance': {'state': 'close'}})
    assert c.get('/api/admin/inbox/connection').json['activated'] is False
    assert c.get('/api/admin/inbox').json['bot'] is False
    fake.state = lambda instance: (200, {'instance': {'state': 'open'}})
    assert c.get('/api/admin/inbox/connection').json['activated'] is True
    assert c.get('/api/admin/inbox').json['bot'] is True


def test_first_message_gets_the_menu_whatever_the_text(shop):
    c, _ = shop
    fake = linked(c)
    assert c.get('/api/admin/whatsapp/status').json['activated']
    assert hook(c, fake, 'quero fazer um pedido').status_code == 200
    assert dispatch_inbox(c.application)['sent'] == 1
    assert '/loja/minha-loja' in fake.calls[-1][2]
    tid = c.get('/api/admin/inbox').json['threads'][0]['id']
    assert c.get(f'/api/admin/inbox/{tid}').json['thread']['state'] == 'open'
    # A segunda mensagem sem palavra-chave chama a equipe, sem repetir o cardápio.
    sql(c, "UPDATE inbox_threads SET last_auto_at='2099-01-01T00:00:00+00:00'")
    assert hook(c, fake, 'tem como caprichar no molho').status_code == 200
    assert dispatch_inbox(c.application)['sent'] == 0
    assert c.get(f'/api/admin/inbox/{tid}').json['thread']['state'] == 'human'


def test_hidden_number_uses_the_alternative_phone(shop):
    c, _ = shop
    fake = linked(c)
    assert c.get('/api/admin/whatsapp/status').json['activated']
    assert hook(c, fake, 'oi', remoteJid='123456789@lid', senderPn='5511988887777@s.whatsapp.net').status_code == 200
    assert dispatch_inbox(c.application)['sent'] == 1
    assert fake.calls[-1][1] == '11988887777'


def test_photo_or_audio_on_first_contact_still_gets_the_menu(shop):
    c, _ = shop
    fake = linked(c)
    assert c.get('/api/admin/whatsapp/status').json['activated']
    body = event()
    body['data']['message'] = {'imageMessage': {'caption': ''}}
    assert c.post('/webhooks/inbox/1', json=body, headers={'X-Webhook-Token': fake.token}).status_code == 200
    assert dispatch_inbox(c.application)['sent'] == 1
    assert '/loja/minha-loja' in fake.calls[-1][2]
    # A segunda foto em seguida chama a equipe.
    body = event()
    body['data']['message'] = {'imageMessage': {'caption': ''}}
    assert c.post('/webhooks/inbox/1', json=body, headers={'X-Webhook-Token': fake.token}).status_code == 200
    tid = c.get('/api/admin/inbox').json['threads'][0]['id']
    assert c.get(f'/api/admin/inbox/{tid}').json['thread']['state'] == 'human'


def test_conversation_left_waiting_goes_back_to_the_robot_after_hours(shop):
    c, _ = shop
    fake = linked(c)
    assert c.get('/api/admin/whatsapp/status').json['activated']
    assert hook(c, fake, 'quero falar com um ATENDENTE').status_code == 200
    tid = c.get('/api/admin/inbox').json['threads'][0]['id']
    assert c.get(f'/api/admin/inbox/{tid}').json['thread']['state'] == 'human'
    assert hook(c, fake, 'oi').status_code == 200 and dispatch_inbox(c.application)['sent'] == 0
    sql(c, "UPDATE inbox_threads SET updated_at='2026-01-01T00:00:00+00:00'")
    assert hook(c, fake, 'oi').status_code == 200
    assert dispatch_inbox(c.application)['sent'] == 1
    assert '/loja/minha-loja' in fake.calls[-1][2]
