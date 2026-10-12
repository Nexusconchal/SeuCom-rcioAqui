// Suporte: conversa da loja com o SeuComércioAqui (painel da loja) e caixa de entrada na Central do Dono.
import { $, $$, api, icon, esc, date, toast, empty } from './ui.js';

const WAIT_NOTICE='Respondemos em até <b>12 horas</b>. Quando a resposta chegar, ela aparece aqui e você recebe um aviso no painel.';

function bubbles(messages,mine){
  if(!messages.length)return '';
  return messages.map(m=>{
    const own=mine(m);
    return '<div class="support-msg '+(own?'own':'other')+'"><div class="support-bubble">'+
      (m.kind==='problem'?'<span class="badge tiny amber">Problema'+(m.topic?' • '+esc(m.topic):'')+'</span>':'')+
      '<p>'+esc(m.body).replace(/\n/g,'<br>')+'</p><small>'+(own?'':esc(m.from_platform?'Suporte SeuComércioAqui':(m.author||'Loja'))+' • ')+date(m.created_at)+'</small></div></div>';
  }).join('');
}
function scrollEnd(box,force){if(force||box.scrollHeight-box.scrollTop-box.clientHeight<120)box.scrollTop=box.scrollHeight;}
// Atualiza a conversa a cada 5 s enquanto ela estiver na tela; run() devolve false para parar.
function poll(box,run){const tick=async()=>{if(!box.isConnected)return;if(!document.hidden&&await run().catch(()=>true)===false)return;setTimeout(tick,5000);};setTimeout(tick,5000);}

export async function supportPage(root){
  const first=await api('/api/admin/support');
  const topics=Object.entries(first.topics);
  root.innerHTML='<section class="panel support-chat"><div class="notice support-wait">'+icon('clock')+'<span>'+WAIT_NOTICE+'</span></div>'+
    '<div class="support-thread" id="support-thread" aria-live="polite"></div>'+
    '<form id="support-form" class="support-form"><div class="chips" role="radiogroup" aria-label="Tipo de mensagem"><button type="button" class="chip active" data-kind="chat">Conversar</button><button type="button" class="chip" data-kind="problem">Relatar um problema</button></div>'+
    '<label id="support-topic-label" hidden>Sobre o quê?<select name="topic">'+topics.map(([k,v])=>'<option value="'+k+'">'+esc(v)+'</option>').join('')+'</select></label>'+
    '<label><span class="sr-only">Mensagem</span><textarea name="body" rows="3" maxlength="2000" required placeholder="Escreva sua mensagem…"></textarea></label>'+
    '<div class="support-actions"><small class="muted">Ctrl + Enter envia</small><button class="btn" type="submit">Enviar</button></div></form></section>';
  const box=$('#support-thread'),form=$('#support-form');let kind='chat',count=-1;
  const draw=(messages,force)=>{if(messages.length===count&&!force)return;count=messages.length;
    box.innerHTML=messages.length?bubbles(messages,m=>!m.from_platform):empty('Fale com a gente','Tire uma dúvida, mande uma sugestão ou relate um problema. A conversa fica salva aqui.');
    scrollEnd(box,force);};
  draw(first.messages,true);
  $$('[data-kind]',form).forEach(b=>b.onclick=()=>{kind=b.dataset.kind;$$('[data-kind]',form).forEach(x=>x.classList.toggle('active',x===b));$('#support-topic-label').hidden=kind!=='problem';
    form.body.placeholder=kind==='problem'?'Conte o que aconteceu, em qual pedido ou tela, e o que você esperava.':'Escreva sua mensagem…';});
  form.body.onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))form.requestSubmit();};
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
    try{const r=await api('/api/admin/support',{method:'POST',body:JSON.stringify({kind,topic:kind==='problem'?form.topic.value:'',body:form.body.value})});
      form.body.value='';draw(r.messages,true);toast('Mensagem enviada! Respondemos em até 12 horas.');}
    catch(err){toast(err.message);}button.disabled=false;form.body.focus();};
  poll(box,async()=>draw((await api('/api/admin/support')).messages));
}

export async function platformSupportView(root,onUnread){
  let current=null;
  root.innerHTML='<div class="support-inbox"><aside class="panel support-list" id="support-list"><div class="loading small-loading">Carregando…</div></aside><section class="panel support-chat" id="support-room">'+empty('Escolha uma conversa','As mensagens das lojas aparecem na lista.')+'</section></div>';
  async function list(){
    const r=await api('/api/platform/support');onUnread&&onUnread(r.unread);
    $('#support-list').innerHTML=r.threads.length?r.threads.map(t=>'<button class="support-item'+(t.id===current?' active':'')+'" data-store="'+t.id+'"><b>'+esc(t.name)+'</b>'+(t.unread?'<span class="badge tiny red">'+t.unread+'</span>':'')+
      '<small>'+(t.last_from_platform?'Você: ':'')+esc((t.last_body||'').slice(0,80))+'</small><small class="muted">'+date(t.last_at)+'</small></button>').join(''):'<p class="muted">Nenhuma mensagem ainda.</p>';
    $$('[data-store]').forEach(b=>b.onclick=()=>open(Number(b.dataset.store)));
  }
  async function open(sid){
    current=sid;const r=await api('/api/platform/support/'+sid);
    $('#support-room').innerHTML='<div class="support-room-head"><div><b>'+esc(r.store.name)+'</b><small class="muted">/loja/'+esc(r.store.slug)+(r.store.phone?' • '+esc(r.store.phone):'')+'</small></div>'+
      (r.store.phone?'<a class="btn secondary small" target="_blank" rel="noopener" href="https://wa.me/'+r.store.phone.replace(/\D/g,'').replace(/^(?!55)/,'55')+'">WhatsApp</a>':'')+'</div>'+
      '<div class="support-thread" id="support-thread"></div><form id="support-reply" class="support-form"><label><span class="sr-only">Resposta</span><textarea name="body" rows="3" maxlength="2000" required placeholder="Responder '+esc(r.store.name)+'…"></textarea></label><div class="support-actions"><small class="muted">Ctrl + Enter envia • a loja recebe um aviso</small><button class="btn" type="submit">Responder</button></div></form>';
    const box=$('#support-thread'),form=$('#support-reply');let count=-1;
    const draw=(messages,force)=>{if(messages.length===count&&!force)return;count=messages.length;box.innerHTML=bubbles(messages,m=>!!m.from_platform);scrollEnd(box,force);};
    draw(r.messages,true);list();
    form.body.onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))form.requestSubmit();};
    form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
      try{const x=await api('/api/platform/support/'+sid,{method:'POST',body:JSON.stringify({body:form.body.value})});form.body.value='';draw(x.messages,true);list();}catch(err){toast(err.message);}button.disabled=false;};
    poll(box,async()=>{if(current!==sid)return false;draw((await api('/api/platform/support/'+sid)).messages);});
  }
  await list();
  const tick=async()=>{if(!root.isConnected||!$('#support-list'))return;if(!document.hidden)await list().catch(()=>{});setTimeout(tick,8000);};setTimeout(tick,8000);
}
