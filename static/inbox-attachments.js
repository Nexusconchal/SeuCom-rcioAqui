import { $, $$, api, esc, modal, closeModal, bindForm, toast } from './ui.js';

export function mediaMarkup(message){
  const media=message.media;
  if(!media)return '';
  if(media.available===false)return '<p class="inbox-media-expired">Arquivo fora do prazo de retenção. Confira no WhatsApp.</p>';
  return '<button type="button" class="inbox-media-button" data-open-media="'+message.id+'" data-kind="'+esc(media.kind)+'">'+(media.kind==='image'?'Visualizar foto':'Ouvir áudio')+'<small>'+esc(media.name||'Arquivo da conversa')+'</small></button>';
}

export function bindMediaButtons(target){
  $$('[data-open-media]',target).forEach(b=>b.onclick=()=>{
    const url='/api/admin/inbox/messages/'+Number(b.dataset.openMedia)+'/media';
    const d=modal(b.dataset.kind==='image'?'Foto da conversa':'Áudio da conversa',
      '<p class="muted">Arquivo disponível somente para a equipe desta loja.</p>'+(b.dataset.kind==='image'?'<img class="inbox-media-image" src="'+url+'" alt="Foto recebida ou enviada na conversa">':'<audio class="inbox-media-audio" controls preload="none" src="'+url+'">Seu navegador não reproduz este áudio.</audio>')+'<p class="muted" id="inbox-media-error" role="status" hidden>Não foi possível abrir. O arquivo pode ter expirado no serviço; confira no WhatsApp.</p>');
    const media=$('img,audio',d);media.onerror=()=>{if(d.open)$('#inbox-media-error',d).hidden=false;};
    d.addEventListener('close',()=>{if(media.tagName==='AUDIO')media.pause();media.removeAttribute('src');},{once:true});
  });
}

export function attachmentDialog(tid,allowed,done){
  if(!allowed())return toast('Assuma a conversa e confira a conexão e a autorização de envio.');
  const key=crypto.randomUUID();
  const d=modal('Enviar foto ou áudio','<p class="muted">Escolha um arquivo de até 4 MB. Confira o destinatário antes de confirmar. O envio só começa após clicar no botão abaixo.</p><form id="inbox-attachment-form"><label>Foto ou áudio<input name="file" type="file" required accept="image/jpeg,image/png,image/webp,audio/ogg,audio/mpeg,audio/wav,audio/mp4,audio/webm"></label><p id="inbox-file-description" class="muted" role="status"></p><label>Legenda opcional<textarea name="caption" maxlength="1000" placeholder="Uma mensagem para acompanhar a foto"></textarea></label><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Confirmar envio do arquivo</button></form>');
  const file=$('[name=file]',d),caption=$('[name=caption]',d),formElement=$('#inbox-attachment-form',d);
  const active=()=>d.open&&d.contains(formElement);
  file.onchange=()=>{
    const f=file.files[0];$('#inbox-file-description',d).textContent=f?f.name+' • '+(f.size/1024).toLocaleString('pt-BR',{maximumFractionDigits:0})+' KB':'';
    file.setCustomValidity(f&&f.size>4*1024*1024?'O limite é 4 MB.':'');
    const audio=f?.type.startsWith('audio/');caption.disabled=!!audio;if(audio)caption.value='';
    caption.placeholder=audio?'Para acompanhar o áudio, envie o texto em uma mensagem separada.':'Uma mensagem para acompanhar a foto';
  };
  bindForm($('#inbox-attachment-form',d),async form=>{
    if(!allowed())throw new Error('A conversa ou a autorização de envio mudou. Confira antes de enviar.');
    const chosen=form.get('file');if(!chosen?.size||chosen.size>4*1024*1024)throw new Error('Escolha um arquivo de até 4 MB.');
    await api('/api/admin/inbox/'+tid+'/attachment',{method:'POST',headers:{'Idempotency-Key':key},body:form});
    if(active())closeModal();toast('Arquivo registrado na fila de envio.');await done();
  });
}
