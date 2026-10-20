"""Private, bounded WhatsApp photos/audio. No remote media URL reaches the browser."""
import base64
import binascii
import hashlib
import io
import json
import re
from datetime import datetime,timedelta,timezone

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_MEDIA = 4 * 1024 * 1024
STORE_MEDIA_BUDGET = 48 * 1024 * 1024  # encoded payloads, checked inside the queue transaction
MIMES = {'image/jpeg', 'image/png', 'image/webp', 'audio/ogg', 'audio/mpeg',
         'audio/wav', 'audio/mp4', 'audio/webm'}


def normalized_mime(value):
    value = str(value or '').split(';')[0].strip().lower()
    return {'audio/mp3': 'audio/mpeg', 'audio/x-wav': 'audio/wav', 'audio/x-m4a': 'audio/mp4'}.get(value, value)


def filename(value, mime):
    extension = {'image/jpeg':'jpg','image/png':'png','image/webp':'webp','audio/ogg':'ogg',
                 'audio/mpeg':'mp3','audio/wav':'wav','audio/mp4':'m4a','audio/webm':'webm'}[mime]
    stem = re.sub(r'[^a-zA-Z0-9_-]', '_', str(value or '').replace('\\', '/').split('/')[-1].rsplit('.', 1)[0])[:50]
    return (stem or ('foto' if mime.startswith('image/') else 'audio')) + '.' + extension


def validate_media(raw, mime, name=''):
    mime = normalized_mime(mime)
    if mime not in MIMES or not raw or len(raw) > MAX_MEDIA:
        raise ValueError('Use foto ou áudio com até 4 MB.')
    if mime.startswith('image/'):
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG','JPEG','WEBP') or image.width * image.height > 20_000_000:
                    raise ValueError('Foto inválida ou muito grande.')
                image.load()
                picture = ImageOps.exif_transpose(image)
                picture.thumbnail((1800,1800))
                output = io.BytesIO()
                picture.convert('RGB').save(output, 'WEBP', quality=85)
                raw, mime = output.getvalue(), 'image/webp'
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError('Envie uma foto PNG, JPEG ou WebP válida.') from None
    else:
        valid = ((mime == 'audio/ogg' and raw.startswith(b'OggS') and (b'OpusHead' in raw[:4096] or b'vorbis' in raw[:4096])) or
                 (mime == 'audio/mpeg' and (raw.startswith(b'ID3') or (len(raw)>2 and raw[0]==255 and raw[1]&224==224))) or
                 (mime == 'audio/wav' and len(raw)>12 and raw.startswith(b'RIFF') and raw[8:12]==b'WAVE') or
                 (mime == 'audio/mp4' and len(raw)>12 and raw[4:8]==b'ftyp') or
                 (mime == 'audio/webm' and raw.startswith(b'\x1aE\xdf\xa3') and b'webm' in raw[:4096]))
        if not valid:
            raise ValueError('O conteúdo não corresponde a um áudio aceito (OGG, MP3, WAV, M4A ou WebM).')
    return {'kind':'image' if mime.startswith('image/') else 'audio','mime':mime,
            'name':filename(name,mime),'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'base64':base64.b64encode(raw).decode('ascii')}


def incoming_media(content, key, view_once=False):
    if view_once:
        return None
    for field, kind in (('imageMessage','image'),('audioMessage','audio')):
        item=content.get(field)
        if not isinstance(item,dict):
            continue
        if item.get('viewOnce'):return None
        mime=normalized_mime(item.get('mimetype'))
        if mime not in MIMES or not mime.startswith(kind+'/'):
            return None
        length=item.get('fileLength',0)
        if isinstance(length,dict):
            if length.get('high',0):return None
            length=length.get('low',0)
        if type(length) is not int or length<0 or length>MAX_MEDIA:
            return None
        # Only an ID/peer selector is retained. Evolution resolves its own stored message.
        return {'kind':kind,'mime':mime,'name':filename(item.get('fileName'),mime),'size':length,
                'key':{'id':key['id'],'remoteJid':key.get('remoteJidAlt') if key.get('remoteJid','').endswith('@lid') else key['remoteJid'],'fromMe':False}}
    return None


def read_media(value):
    try:
        data=json.loads(value or '{}')
        return data if isinstance(data,dict) and data.get('kind') in ('image','audio') and data.get('mime') in MIMES else None
    except (ValueError,TypeError):
        return None


def public_media(row):
    data=read_media(row['media'])
    if not data:return None
    return {key:data[key] for key in ('kind','mime','name','size')} | {'available':not data.get('expired',False),'url':f"/api/admin/inbox/messages/{row['id']}/media"}


def cleanup_media(conn):
    """Release completed upload bytes after seven days, preserving the conversation.

    Pending/uncertain sends require review and continue counting against the budget.
    Four payloads per tick keep memory/transaction work bounded.
    """
    cutoff=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec='seconds')
    rows=conn.execute("SELECT id,media FROM inbox_messages WHERE direction='out' AND status IN ('sent','cancelled') AND COALESCE(sent_at,created_at)<? AND media_data!='' ORDER BY id LIMIT 4",(cutoff,)).fetchall()
    for row in rows:
        data=read_media(row['media'])
        if not data:continue
        data['expired']=True
        conn.execute("UPDATE inbox_messages SET media=?,media_data='' WHERE id=? AND status IN ('sent','cancelled')",(json.dumps(data,separators=(',',':')),row['id']))
    return len(rows)


def decode_provider(result, expected_kind):
    encoded=result.get('base64') if isinstance(result,dict) else None
    if not isinstance(encoded,str) or len(encoded)>((MAX_MEDIA+2)//3)*4+200:
        raise ValueError('Mídia indisponível ou acima do limite.')
    if encoded.startswith('data:'):
        header,_,encoded=encoded.partition(',')
        if ';base64' not in header:raise ValueError('Formato inválido.')
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise ValueError('Mídia inválida.') from None
    data=validate_media(raw,result.get('mimetype'),result.get('fileName',''))
    if data['kind']!=expected_kind:raise ValueError('Tipo de mídia diferente do recebido.')
    return data
