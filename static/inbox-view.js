import { $, $$, api, esc, date, icon, toast, auth, bindForm, modal, closeModal } from './ui.js';
import { matchesSearch } from './search.js';
import { manualOrder } from './management.js';

const send=(path,value,method='POST')=>api(path,{method,body:JSON.stringify(value)});
const labels={received:'Recebida',queued:'Na fila',processing:'Enviando',sent:'Aceita pelo serviço',uncertain:'Confira no WhatsApp',cancelled:'Cancelada',held:'Aguardando revisão'};
const stateLabel=t=>t.state==='closed'?'Encerrada':t.assigned_name?'Com '+t.assigned_name:t.state==='human'?'Precisa de atendente':'Disponível';
const avatar=name=>esc((name||'?').slice(0,1).toLocaleUpperCase('pt-BR'));

export async function inboxPage(root){
  root._inboxCleanup?.();
  const view=Symbol('inbox');root._inboxView=view;
  let stopped=false,timer,busy=false,data,selected=null,thread=null,filter='open',query='',requestVersion=0,connection={connected:null,state:'checking'};
  let messages=new Map(),quick=[],hasMore=false,formIdentity='',connectionCheckedAt=0;
  const drafts=root._inboxDrafts??=new Map();
  const alive=()=>!stopped&&root.isConnected&&root.dataset.management==='inbox'&&root._inboxView===view;
  root._inboxCleanup=()=>{stopped=true;clearTimeout(timer);};
  data=await api('/api/admin/inbox');if(!alive())return;
  root.innerHTML='<section class="inbox-hero"><div><span class="eyebrow">ATENDIMENTO DA SUA LOJA</span><h2>Uma boa conversa<br>faz o cliente voltar.</h2><p>Bot e equipe trabalhando juntos, com cada resposta no lugar.</p></div><div class="inbox-hero-actions"><button type="button" class="btn secondary" id="inbox-settings">'+icon('gear')+' Respostas e atalhos</button><button type="button" class="btn secondary" id="refresh-inbox">'+icon('clock')+' Atualizar</button><small id="inbox-sync" role="status">Atualização automática a cada 5 segundos</small></div></section>'+
    '<section class="panel inbox-connection"><div class="inbox-connection-head"><div><span class="eyebrow">CONEXÃO E ENVIO</span><h2>WhatsApp da loja</h2></div><div class="row-actions"><button type="button" class="btn secondary small" id="inbox-connection-action"></button><button type="button" class="btn small" id="inbox-delivery-action"></button></div></div><div class="inbox-status-grid" id="inbox-status-grid"></div><div class="inbox-bot-row"><label class="check-row"><span><input id="inbox-bot" type="checkbox"> Respostas automáticas do bot</span></label><button type="button" class="text-link" id="inbox-preview">Testar resposta '+icon('arrow')+'</button></div><p class="muted" id="inbox-operation-note"></p></section>'+
    '<div class="inbox-workspace" id="inbox-workspace"><section class="panel inbox-list"><div class="section-heading"><h2>Conversas</h2><span class="badge gray" id="inbox-count"></span></div><label class="search">'+icon('search')+'<input type="search" id="inbox-search" aria-label="Buscar conversa" placeholder="Nome, telefone ou mensagem"></label><div class="inbox-filters" id="inbox-filters"></div><div class="inbox-contacts" id="inbox-contacts"></div></section><section class="panel inbox-conversation" id="inbox-conversation"><div class="inbox-empty"><span>'+icon('bell')+'</span><h3>Seu próximo atendimento começa aqui</h3><p>Escolha uma conversa. Assuma o atendimento, use uma resposta pronta ou monte o pedido enquanto conversa.</p></div></section></div>';
  $('#inbox-settings',root).hidden=!data.permissions.configure;
  $('#inbox-preview',root).hidden=!data.permissions.configure;
  $('#refresh-inbox',root).onclick=async()=>{await load();await checkConnection();};
  $('#inbox-search',root).oninput=e=>{query=e.target.value;drawContacts();};
  $('#inbox-settings',root).onclick=()=>settingsDialog(data.settings,load);
  $('#inbox-preview',root).onclick=previewDialog;
  $('#inbox-bot',root).onchange=async e=>{try{await send('/api/admin/inbox/bot',{enabled:e.target.checked},'PUT');await load();}catch(err){e.target.checked=!e.target.checked;toast(err.message);}};
  $('#inbox-connection-action',root).onclick=connectionAction;
  $('#inbox-delivery-action',root).onclick=()=>{
    const enabled=!data.sending;
    const d=modal(enabled?'Autorizar envio das respostas?':'Pausar novos envios?',
      '<p>'+(enabled?'As respostas que você enviar e as respostas do bot ativado poderão sair pelo WhatsApp conectado desta loja. Mensagens antigas ficam para revisão individual.':'As próximas mensagens ficam pausadas. Um envio já em processamento pode concluir. O bot também será desligado.')+'</p><p class="muted">Isso não agenda campanhas de marketing.</p><button type="button" class="btn full" id="confirm-inbox-delivery">'+(enabled?'Autorizar novos envios':'Pausar envio')+'</button>');
    $('#confirm-inbox-delivery',d).onclick=async e=>{e.currentTarget.disabled=true;try{await send('/api/admin/inbox/delivery',{enabled},'PUT');closeModal();await load();toast(enabled?'Novos envios autorizados. Pendências antigas precisam de revisão.':'Envio pausado.');}catch(err){toast(err.message);if(d.open)$('#confirm-inbox-delivery',d).disabled=false;}};
  };
  function drawStatus(){
    if(!alive())return;
    const tile=(label,value,ok)=>'<div><span class="inbox-status-dot '+(ok?'ready':'')+'"></span><small>'+label+'</small><b>'+value+'</b></div>';
    $('#inbox-status-grid',root).innerHTML=tile('Número',connection.connected?'Conectado':connection.state==='checking'?'Verificando…':data.linked?'Conferir conexão':'Não vinculado',connection.connected)+tile('Conversas',data.configured?'Recebimento ativado':'Recebimento desativado',data.configured)+tile('Envio',data.sending?'Autorizado pela loja':'Pausado',data.sending)+tile('Processamento',data.delivery.running?'Disponível':'Aguardando serviço',data.delivery.running);
    const connect=$('#inbox-connection-action',root);connect.textContent=!data.linked?'Conectar WhatsApp':!data.configured?'Ativar conversas':'Ver conexão / QR';connect.disabled=!data.permissions.connect||!data.provider_available;
    const delivery=$('#inbox-delivery-action',root);delivery.textContent=data.sending?'Pausar envio':'Autorizar envio';delivery.disabled=!data.permissions.connect||!data.configured||(!data.sending&&!connection.connected);
    const bot=$('#inbox-bot',root);bot.checked=data.bot;bot.disabled=!data.permissions.configure||!data.configured;
    $('#inbox-operation-note',root).textContent=((data.queue.queued||0)+(data.queue.processing||0))+' resposta(s) na fila • '+((data.queue.held||0)+(data.queue.uncertain||0))+' para conferir. '+(!data.provider_available?'O serviço de WhatsApp precisa ser configurado pela plataforma. ':!data.permissions.connect?'O dono gerencia a conexão e a autorização de envio. ':!data.sending?'Autorize o envio para liberar novas respostas. ':!connection.connected?'Confira a conexão antes de responder. ':'')+'ATENDENTE e mensagens de mídia chamam a equipe. Assumir uma conversa pausa o bot.';
    syncSendButton();
  }
  function drawContacts(){
    const accepts=t=>filter==='all'||(filter==='open'?t.state!=='closed':filter==='unread'?t.unread>0:filter==='human'?t.state==='human'&&!t.assigned_to:filter==='mine'?t.assigned_to===auth.user.id:t.state==='closed');
    const list=data.threads.filter(t=>accepts(t)&&matchesSearch(query,[t.name,t.phone,t.last_body]));
    $('#inbox-count',root).textContent=data.threads.length+(data.threads.length===200?' recentes':'');
    $('#inbox-filters',root).innerHTML=[['open','Abertas'],['unread','Não lidas'],['human','Aguardando'],['mine','Minhas'],['closed','Encerradas'],['all','Todas']].map(([id,label])=>'<button type="button" class="chip '+(filter===id?'active':'')+'" data-inbox-filter="'+id+'" aria-pressed="'+(filter===id)+'">'+label+'</button>').join('');
    $$('[data-inbox-filter]',root).forEach(b=>b.onclick=()=>{filter=b.dataset.inboxFilter;drawContacts();});
    const html=list.length?list.map(t=>'<button type="button" class="inbox-contact '+(selected===t.id?'selected':'')+' '+(t.state==='human'&&!t.assigned_to?'needs-human':'')+'" data-thread="'+t.id+'" aria-pressed="'+(selected===t.id)+'"><span class="inbox-avatar">'+avatar(t.name)+'</span><span class="inbox-contact-copy"><b>'+esc(t.name)+'</b><small>'+esc(t.phone)+'</small><span class="inbox-snippet">'+(t.last_direction==='out'?'Você: ':'')+esc(t.last_body||'Sem mensagem')+'</span><em>'+esc(stateLabel(t))+'</em></span>'+(t.unread?'<span class="inbox-unread">'+t.unread+'</span>':'')+'</button>').join(''):'<div class="inbox-list-empty"><p>Nenhuma conversa neste filtro.</p><small>As mensagens recebidas após ativar a conexão aparecem aqui.</small></div>';
    const contacts=$('#inbox-contacts',root);if(contacts.innerHTML!==html)contacts.innerHTML=html;
    $$('[data-thread]',root).forEach(b=>b.onclick=()=>selectThread(Number(b.dataset.thread)));
  }
  function draft(){if(!drafts.has(selected))drafts.set(selected,{text:'',key:crypto.randomUUID()});return drafts.get(selected);}
  async function selectThread(tid){selected=tid;messages=new Map();hasMore=false;formIdentity='';drawContacts();$('#inbox-workspace',root).classList.add('inbox-chat-open');await openThread();}
  function syncSendButton(){const b=$('#inbox-send',root);if(b)b.disabled=!!$('#inbox-reply',root)?.dataset.busy||!thread?.mine||!data.sending||connection.connected!==true;}
  async function openThread(older=false){
    if(!selected||!alive())return;
    const tid=selected,version=++requestVersion;
    try{const before=older&&messages.size?Math.min(...messages.keys()):null;
      const r=await api('/api/admin/inbox/'+tid+(before?'?before='+before:''));if(!alive()||selected!==tid||version!==requestVersion)return;
      thread=r.thread;quick=r.quick_replies;hasMore=older?r.has_more:(messages.size>100?hasMore:r.has_more);
      r.messages.forEach(m=>messages.set(m.id,m));drawConversation(older);
    }catch(e){if(alive())toast(e.message);}
  }
  function drawConversation(older=false){
    const t=thread,target=$('#inbox-conversation',root),identity=[t.id,t.assigned_to,t.state,data.sending].join(':');
    if(identity!==formIdentity&&!$('#inbox-reply',target)?.dataset.busy){
      const saved=draft();formIdentity=identity;
      target.innerHTML='<div class="inbox-chat-head"><button type="button" class="icon-btn inbox-back" id="inbox-back" aria-label="Voltar às conversas">'+icon('back')+'</button><span class="inbox-avatar">'+avatar(t.name)+'</span><div><h2>'+esc(t.name)+'</h2><p>'+esc(t.phone)+' • '+esc(stateLabel(t))+'</p></div><div class="inbox-chat-actions"><button type="button" id="claim-inbox" class="btn secondary small">'+(t.mine?'Liberar conversa':'Assumir conversa')+'</button><button type="button" id="inbox-order" class="btn secondary small">'+icon('plus')+' Montar pedido</button><button type="button" id="close-inbox" class="text-link">Encerrar</button></div></div>'+
        (data.permissions.configure?'<div class="inbox-assignment"><label>Responsável<select id="inbox-assignee" aria-label="Responsável pela conversa"><option value="">Escolha um atendente</option>'+data.agents.map(a=>'<option value="'+a.id+'" '+(a.id===t.assigned_to?'selected':'')+'>'+esc(a.name)+'</option>').join('')+'</select></label><button type="button" class="btn secondary small" id="inbox-assign">Transferir</button></div>':'')+
        '<div class="inbox-history" aria-label="Histórico da conversa"></div><form id="inbox-reply"><div id="inbox-quick-replies" class="inbox-quick-replies"></div><label>Resposta<textarea name="message" maxlength="4000" required '+(!t.mine?'disabled':'')+' placeholder="'+(t.mine?'Escreva ou use / para uma resposta rápida':'Assuma a conversa para responder')+'">'+esc(saved.text)+'</textarea></label><p class="form-error" role="alert" hidden></p><div class="inbox-compose-bottom"><small>'+(t.mine?'Ctrl + Enter para enviar. Revise antes de confirmar.':'O bot fica pausado durante o atendimento humano.')+'</small><button class="btn" id="inbox-send" type="submit">Enviar resposta '+icon('arrow')+'</button></div></form>';
      $('#inbox-back',target).onclick=()=>{selected=null;thread=null;$('#inbox-workspace',root).classList.remove('inbox-chat-open');drawContacts();};
      $('#claim-inbox',target).onclick=async()=>{try{await send('/api/admin/inbox/'+t.id+'/claim',{claim:!t.mine});await load();}catch(e){toast(e.message);}};
      $('#close-inbox',target).onclick=async()=>{try{await send('/api/admin/inbox/'+t.id+'/close',{});await load();toast('Conversa encerrada.');}catch(e){toast(e.message);}};
      $('#inbox-order',target).onclick=()=>manualOrder(()=>toast('Pedido criado. Acompanhe em Pedidos.'),{customer:t.name,phone:t.phone});
      if($('#inbox-assign',target))$('#inbox-assign',target).onclick=async()=>{const id=Number($('#inbox-assignee',target).value);if(!id)return toast('Escolha o atendente.');try{await send('/api/admin/inbox/'+t.id+'/assign',{user_id:id});await load();}catch(e){toast(e.message);}};
      const input=$('[name=message]',target);
      input.oninput=()=>{drafts.set(t.id,{text:input.value,key:crypto.randomUUID()});drawQuickReplies();};
      input.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!$('#inbox-send',target).disabled){e.preventDefault();$('#inbox-reply',target).requestSubmit();}};
      bindForm($('#inbox-reply',target),async f=>{const saved=drafts.get(t.id);try{await api('/api/admin/inbox/'+t.id+'/reply',{method:'POST',headers:{'Idempotency-Key':saved.key},body:JSON.stringify({message:f.get('message')})});if(drafts.get(t.id)?.key===saved.key){drafts.set(t.id,{text:'',key:crypto.randomUUID()});if(input.isConnected)input.value='';}toast('Resposta registrada na fila de envio.');await openThread();}finally{setTimeout(()=>{if(alive())syncSendButton();},0);}});
    }
    const history=$('.inbox-history',target),nearBottom=history.scrollHeight-history.scrollTop-history.clientHeight<70,oldHeight=history.scrollHeight;
    const html=(hasMore?'<button type="button" class="btn secondary small inbox-older" id="inbox-older">Carregar mensagens anteriores</button>':'')+[...messages.values()].sort((a,b)=>a.id-b.id).map(m=>'<article class="inbox-bubble '+(m.direction==='out'?'out':'in')+' '+(['uncertain','held'].includes(m.status)?'needs-review':'')+'"><p>'+esc(m.body)+'</p><small>'+date(m.created_at)+' • '+(m.automated?'Bot • ':'')+esc(labels[m.status]||m.status)+'</small>'+(t.mine&&m.direction==='out'&&['held','queued'].includes(m.status)?'<div class="inbox-message-actions">'+(m.status==='held'&&data.sending&&!m.automated?'<button type="button" class="text-link" data-inbox-message="'+m.id+'" data-action="queue">Revisei, colocar na fila</button>':'')+'<button type="button" class="text-link" data-inbox-message="'+m.id+'" data-action="cancel">Cancelar pendência</button></div>':'')+(m.status==='uncertain'?'<p class="inbox-message-note">Confira no WhatsApp antes de reenviar. O resultado não foi confirmado.</p>':'')+'</article>').join('');
    if(history.innerHTML!==html){history.innerHTML=html;if(older)history.scrollTop+=history.scrollHeight-oldHeight;else if(nearBottom||!history.dataset.loaded)history.scrollTop=history.scrollHeight;history.dataset.loaded='1';}
    if($('#inbox-older',target))$('#inbox-older',target).onclick=()=>openThread(true);
    $$('[data-inbox-message]',target).forEach(b=>b.onclick=async()=>{try{await send('/api/admin/inbox/messages/'+b.dataset.inboxMessage+'/action',{action:b.dataset.action});await load();}catch(e){toast(e.message);}});
    drawQuickReplies();syncSendButton();
  }
  function drawQuickReplies(){
    const box=$('#inbox-quick-replies',root),input=$('#inbox-reply textarea',root);if(!box||!input)return;
    const term=input.value.startsWith('/')?input.value.slice(1).toLocaleLowerCase('pt-BR'):'';
    box.innerHTML=quick.filter(r=>!term||r.shortcut.includes(term)).map(r=>'<button type="button" class="chip" data-quick-reply="'+esc(r.shortcut)+'" '+(!thread.mine?'disabled':'')+' title="'+esc(r.name)+'">/'+esc(r.shortcut)+'</button>').join('');
    $$('[data-quick-reply]',box).forEach(b=>b.onclick=()=>{const value=quick.find(r=>r.shortcut===b.dataset.quickReply);input.value=input.value.startsWith('/')?value.rendered:input.value+(input.value?'\n':'')+value.rendered;drafts.set(selected,{text:input.value,key:crypto.randomUUID()});input.focus();drawQuickReplies();});
  }
  async function load(){
    if(!alive()||busy)return;busy=true;
    try{const next=await api('/api/admin/inbox');if(!alive())return;data=next;if(selected&&!data.threads.some(t=>t.id===selected)){selected=null;thread=null;messages.clear();formIdentity='';$('#inbox-conversation',root).innerHTML='<div class="inbox-empty"><p>Esta conversa não está mais disponível. Escolha outra na lista.</p></div>';$('#inbox-workspace',root).classList.remove('inbox-chat-open');}drawStatus();drawContacts();if(selected)await openThread();$('#inbox-sync',root).textContent='Atualizado agora • atualização automática';}
    catch(e){if(alive()){if(e.status===401){root._inboxCleanup();location.href='/entrar';return;}$('#inbox-sync',root).textContent='Atualização interrompida. Tentando novamente…';}}finally{busy=false;}
  }
  async function checkConnection(){connectionCheckedAt=Date.now();try{const result=await api('/api/admin/inbox/connection');if(alive()){connection=result;drawStatus();}}catch{if(alive()){connection={connected:false,state:'unknown'};drawStatus();}}}
  async function connectionAction(){
    if(data.linked&&!data.configured){try{await send('/api/admin/inbox/connect',{});await load();await checkConnection();toast('Recebimento de conversas ativado.');}catch(e){toast(e.message);}return;}
    const d=modal('Conectar o WhatsApp da loja','<p>No celular da loja, abra WhatsApp → Aparelhos conectados → Conectar aparelho.</p><div id="inbox-qr"></div><button type="button" class="btn secondary full" id="inbox-create-qr">Gerar QR Code</button><button type="button" class="btn full" id="inbox-confirm-qr">Já conectei, verificar</button>');
    $('#inbox-create-qr',d).onclick=async e=>{e.currentTarget.disabled=true;try{const r=await send('/api/admin/whatsapp/connect',{});if(!d.open)return;$('#inbox-qr',d).innerHTML=(r.qr?'<img class="wa-qr" alt="QR Code para conectar WhatsApp" src="'+esc(r.qr)+'" width="240" height="240">':'<p>O serviço não retornou um QR Code. Confira se o número já está conectado.</p>')+(r.pairing_code?'<p>Código: '+esc(r.pairing_code)+'</p>':'');}catch(err){toast(err.message);}finally{if(d.open)$('#inbox-create-qr',d).disabled=false;}};
    $('#inbox-confirm-qr',d).onclick=async()=>{await checkConnection();if(!connection.connected)return toast('A conexão ainda não foi confirmada. Confira o celular e tente novamente.');try{await send('/api/admin/inbox/connect',{});closeModal();await load();toast('WhatsApp conectado e conversas ativadas.');}catch(e){toast(e.message);}};
  }
  function previewDialog(){
    const d=modal('Testar uma resposta do bot','<p class="muted">Simulação interna. Nenhuma mensagem é enviada ao WhatsApp.</p><form id="inbox-simulation"><label>Mensagem do cliente<input name="message" required maxlength="4000" value="Qual o horário?"></label><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Ver resposta</button><div id="inbox-simulation-result" class="message-preview" hidden></div></form>');
    bindForm($('#inbox-simulation',d),async f=>{const r=await send('/api/admin/inbox/preview',{message:f.get('message')});const result=$('#inbox-simulation-result',d);result.hidden=false;result.textContent=r.human?'Essa mensagem chama um atendente humano.':r.reply||'Nenhuma regra corresponde a essa mensagem. A equipe pode atender pelo painel.';});
  }
  function schedule(){timer=setTimeout(async()=>{if(!alive())return;if(!document.hidden){await load();if(Date.now()-connectionCheckedAt>30000)await checkConnection();}if(alive())schedule();},5000);}
  drawStatus();drawContacts();checkConnection();schedule();
}

function settingsDialog(initial,done){
  const settings=structuredClone(initial);
  const d=modal('Respostas do bot e atalhos','<p class="muted">Personalize o atendimento da loja. Salvar não ativa o bot nem envia mensagens.</p><form id="inbox-settings-form"><div class="inbox-settings-tabs"><button type="button" class="chip active" data-settings-tab="rules">Respostas do bot</button><button type="button" class="chip" data-settings-tab="quick_replies">Respostas rápidas</button></div><section id="inbox-rules-settings"><label class="check-row"><span><input name="closed_enabled" type="checkbox" '+(settings.closed_enabled?'checked':'')+'> Responder quando a loja estiver fechada</span></label><label>Mensagem de loja fechada<textarea name="closed_message" required maxlength="1500">'+esc(settings.closed_message)+'</textarea></label><div id="inbox-rule-rows"></div><button type="button" class="btn secondary small" id="inbox-add-rule">'+icon('plus')+' Adicionar resposta</button></section><section id="inbox-quick-settings" hidden><p class="muted">Os atalhos inserem texto na resposta. O atendente revisa e envia.</p><div id="inbox-quick-rows"></div><button type="button" class="btn secondary small" id="inbox-add-quick">'+icon('plus')+' Adicionar atalho</button></section><p class="inbox-variable-help">Variáveis: {nome}, {loja}, {link}, {horario}, {pix}, {entrega}, {minimo}. ATENDENTE e HUMANO sempre chamam a equipe.</p><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Salvar respostas e atalhos</button></form>',true);
  function addRow(family,item){
    const rule=family==='rules',container=$(rule?'#inbox-rule-rows':'#inbox-quick-rows',d);
    const el=document.createElement('fieldset');el.className='inbox-settings-row';el.dataset.family=family;el.dataset.id=item.id||'';
    el.innerHTML='<legend>'+esc(rule?'Resposta do bot':'Atalho')+'</legend><label>Nome<input data-name required maxlength="80" value="'+esc(item.name)+'"></label>'+(rule?'<label>Palavras-chave, separadas por vírgula<input data-keywords required maxlength="550" value="'+esc(item.keywords.join(', '))+'"></label><label class="check-row"><span><input data-enabled type="checkbox" '+(item.enabled?'checked':'')+'> Regra habilitada</span></label>':'<label>Atalho (sem /)<input data-shortcut required pattern="[a-z0-9_-]{1,40}" maxlength="40" value="'+esc(item.shortcut)+'"></label>')+'<label>Mensagem<textarea data-message required maxlength="1500">'+esc(item.message)+'</textarea></label><button type="button" class="text-link" data-remove>Remover '+(rule?'resposta':'atalho')+'</button>';
    container.appendChild(el);$('[data-remove]',el).onclick=()=>el.remove();
  }
  settings.rules.forEach(item=>addRow('rules',item));settings.quick_replies.forEach(item=>addRow('quick_replies',item));
  $('#inbox-add-rule',d).onclick=()=>{if($$('[data-family=rules]',d).length>=12)return toast('Limite de 12 respostas.');addRow('rules',{id:'r-'+crypto.randomUUID().slice(0,8),name:'Nova resposta',keywords:[],enabled:true,message:''});};
  $('#inbox-add-quick',d).onclick=()=>{if($$('[data-family=quick_replies]',d).length>=20)return toast('Limite de 20 atalhos.');addRow('quick_replies',{shortcut:'',name:'Novo atalho',message:''});};
  $$('[data-settings-tab]',d).forEach(b=>b.onclick=()=>{$('#inbox-rules-settings',d).hidden=b.dataset.settingsTab!=='rules';$('#inbox-quick-settings',d).hidden=b.dataset.settingsTab!=='quick_replies';$$('[data-settings-tab]',d).forEach(x=>x.classList.toggle('active',x===b));});
  $('#inbox-settings-form',d).addEventListener('invalid',e=>{const family=e.target.closest('section')?.id;$('[data-settings-tab="'+(family==='inbox-quick-settings'?'quick_replies':'rules')+'"]',d)?.click();},true);
  bindForm($('#inbox-settings-form',d),async f=>{const result={closed_enabled:f.has('closed_enabled'),closed_message:f.get('closed_message'),rules:[],quick_replies:[]};$$('[data-family]',d).forEach(el=>{const family=el.dataset.family,item={name:$('[data-name]',el).value,message:$('[data-message]',el).value};if(family==='rules')Object.assign(item,{id:el.dataset.id,keywords:$('[data-keywords]',el).value.split(',').map(s=>s.trim()).filter(Boolean),enabled:$('[data-enabled]',el).checked});else item.shortcut=$('[data-shortcut]',el).value;result[family].push(item);});await send('/api/admin/inbox/settings',result,'PUT');closeModal();toast('Respostas salvas.');await done();});
}
