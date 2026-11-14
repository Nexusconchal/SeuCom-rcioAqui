import { onlineMethod, merchantPayment, bindMerchantPayment } from './online-payments.js';
import { printDocument } from './printing.js';
import { initPrintJournal, enqueuePrint, pendingPrints, trackedPrint, mountPrintJournal } from './print-journal.js';
import { setupPanel, operationNotices, receivablesPage, operationsHealthPage, installConnectionNotice } from './reliability.js';
import { networkSettings, networkInvite } from './network.js';
import { matchesSearch, productMatches } from './search.js';
import { bindQuickNavigation } from './quick-navigation.js';
import { deliveryMapPage } from './delivery.js';
import { inboxPage } from './inbox.js';
import { managementView, costsDialog, manualOrder, overviewDetails } from './management.js';
import { supportPage } from './support.js';
import { growthPage } from './growth.js';
import { fiscalPage } from './fiscal.js';
import { operationsPage } from './operations.js';
import { inventoryPage } from './inventory.js';
import { $, $$, icon, brand, money, esc, image, api, auth, useTimeZone, modal, closeModal, bindForm, empty, toast, pay, date, attachFallbacks, copy, cents, field, moneyInput, statuses } from './ui.js';
import { openImageBank } from './image-bank.js';
let store, products=[], categories=[], drivers=[], orders=[], tab='overview', period=7, timer, generation=0, role='owner', roleLabel='Dono';
const ROLE_TABS={kitchen:['kitchen','orders','settings','printing','support'],cashier:['overview','pos','cash','dining','reports','inbox','deliverymap','orders','kitchen','customers','drivers','sales','settings','printing','support'],manager:null,owner:null};
export async function renderDashboard(){
  const me=await api('/api/admin/store');store=me.store;useTimeZone(store.timezone);role=me.role;roleLabel=me.role_label;initPrintJournal(store.id,auth.user.id);document.title='Painel • '+store.name;
  $('#app').innerHTML='<div class="dashboard"><header class="dashboard-head">'+brand()+'<nav class="dashboard-nav">'+[['overview','Visão geral'],['orders','Pedidos'],['pos','PDV / Balcão'],['cash','Caixa por turno'],['dining','Mesas e comandas'],['kitchen','Cozinha'],['products','Cardápio'],['stock','Estoque'],['ingredients','Insumos e fichas'],['customers','Clientes'],['inbox','Atendimento WhatsApp'],['marketing','Marketing'],['promotions','Promoções e horários'],['drivers','Entregas'],['deliverymap','Mapa de entregas'],['sales','Vendas e caixa'],['finance','Lucro e custos'],['receivables','Recebíveis online'],['diagnostics','Diagnóstico da loja'],['purchasing','Contas e fornecedores'],['reports','Gerar relatório'],['fiscal','Fiscal'],['integrations','Integrações'],['network','Minha rede'],['printing','Imprimir notinha'],['support','Suporte']].filter(([id])=>role==='owner'||(role==='manager'?!['integrations','network'].includes(id):ROLE_TABS[role].includes(id))).map(([id,label])=>'<button data-tab="'+id+'">'+label+'</button>').join('')+'</nav>'+'<div class="head-actions"><button id="sound-toggle" class="icon-btn sound-toggle" aria-label="Som de novos pedidos">'+icon('bell')+'</button><button class="icon-btn" data-tab="settings" aria-label="Configurações">'+icon('gear')+'</button><button id="logout" class="icon-btn" aria-label="Sair">'+icon('logout')+'</button></div></header><main id="main" class="dashboard-main"><section class="dashboard-title"><div><span class="eyebrow" id="page-kicker">SEU COMÉRCIO EM MOVIMENTO</span><h1 id="page-title">Seu dia em um olhar</h1><p id="page-subtitle">Tudo pronto para vender mais.</p></div><div class="title-actions"><button id="store-toggle" class="badge gray"><i></i>Loja fechada</button><a class="btn" href="/loja/'+esc(store.slug)+'" target="_blank" rel="noopener">Ver minha loja '+icon('eye')+'</a></div></section><section id="platform-notices"></section><section id="operation-notices"></section><section id="dashboard-content" aria-live="polite"></section></main><footer class="dashboard-footer"><span>SeuComércioAqui</span><span>'+esc(store.name)+' • '+esc(auth.user.name)+' ('+esc(roleLabel)+')</span></footer></div>';
  $$('[data-tab]').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
  bindQuickNavigation(switchTab,store.id+'.'+auth.user.id);
  $('#logout').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'});location.href='/entrar';}catch(e){toast(e.message);}};
  $('#store-toggle').onclick=async()=>{try{const result=await api('/api/admin/store/open',{method:'POST',body:JSON.stringify({open:!store.open})});store=result.store;updateStoreButton();toast(store.open?'Loja aberta para pedidos.':'Loja fechada.');platformNotices();}catch(e){toast(e.message);}};
  applyKioskPrinting();updateStoreButton();updateSoundButton();installConnectionNotice();
  document.addEventListener('pointerdown',unlockAudio,{once:true});
  $('#sound-toggle').onclick=()=>{try{localStorage.setItem('sca.sound',soundOn()?'0':'1');}catch{}unlockAudio();updateSoundButton();
    if(soundOn()){chime();if('Notification' in window&&Notification.permission==='default')Notification.requestPermission().catch(()=>{});}
    toast(soundOn()?'Som de novos pedidos ligado.':'Som de novos pedidos desligado.');};
  if(new URLSearchParams(location.search).has('assinatura')){history.replaceState(null,'','/painel');refreshBilling();}else platformNotices();
  watchOrders();
  const startTab=new URLSearchParams(location.search).get('aba')==='suporte'?'support':role==='kitchen'?'kitchen':'overview';
  if(startTab==='support')history.replaceState(null,'','/painel');
  await switchTab(startTab);
  const invitation=new URLSearchParams(location.search).get('rede_convite');if(invitation&&role==='owner')await networkInvite(invitation);
}
function updateStoreButton(){const b=$('#store-toggle');const paused=store.billing_state&&!['exempt','active','paid','trial'].includes(store.billing_state);b.className='badge '+(store.open_now?'green':store.open&&!paused?'amber':'gray');b.innerHTML='<i></i>'+(paused?'Loja pausada (assinatura)':!store.open?'Loja fechada':store.open_now?'Loja aberta':'Aberta • fora do horário');b.title=store.open?'Clique para fechar a loja agora':'Clique para abrir a loja';}
const days=['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'];
let seen=null,motojaSeen=null,watchTimer,audio,journalWarning=false,printSeen=null,watchBusy=false;
let alarmTimer=null,alarmOrders=[];
const soundOn=()=>{try{return localStorage.getItem('sca.sound')!=='0';}catch{return true;}};
function unlockAudio(){try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();audio.resume();}catch{}}
function chime(){
  if(!soundOn()||!audio)return;
  [0,.18,.36].forEach((delay,i)=>{const o=audio.createOscillator(),g=audio.createGain();o.type='sine';o.frequency.value=[880,1175,1568][i];
    g.gain.setValueAtTime(.0001,audio.currentTime+delay);g.gain.exponentialRampToValueAtTime(.35,audio.currentTime+delay+.02);g.gain.exponentialRampToValueAtTime(.0001,audio.currentTime+delay+.35);
    o.connect(g).connect(audio.destination);o.start(audio.currentTime+delay);o.stop(audio.currentTime+delay+.4);});
}
// Alarme de pedido novo: toca sem parar até alguém aceitar (pedido sai de "novo").
function setAlarm(waiting){
  alarmOrders=waiting;
  let bar=$('#order-alarm');
  if(!bar){bar=document.createElement('div');bar.id='order-alarm';bar.className='order-alarm';bar.setAttribute('role','alert');document.body.append(bar);}
  if(!waiting.length){clearInterval(alarmTimer);alarmTimer=null;bar.hidden=true;return;}
  const muted=soundOn()&&(!audio||audio.state!=='running');
  bar.hidden=false;
  bar.innerHTML='<div><b>'+(waiting.length>1?waiting.length+' pedidos esperando você aceitar':'Pedido #'+waiting[0].number+' esperando você aceitar')+'</b><span>'+esc(waiting[0].customer)+' • '+money(waiting[0].total)+(soundOn()?'':' • som desligado')+'</span></div>'+
    (muted?'<button type="button" class="btn secondary small" data-alarm-sound>Ativar som</button>':'')+'<button type="button" class="btn small" data-alarm-open>Ver e aceitar</button>';
  $('[data-alarm-open]',bar).onclick=()=>{unlockAudio();switchTab('orders');};
  const sound=$('[data-alarm-sound]',bar);if(sound)sound.onclick=()=>{unlockAudio();setTimeout(()=>{chime();setAlarm(alarmOrders);},150);};
  if(!alarmTimer){chime();alarmTimer=setInterval(()=>{if(alarmOrders.length)chime();},2500);}
}
// Apita algumas vezes seguidas (pedido aceito sozinho não espera clique, então o aviso precisa chamar atenção).
function ring(times){chime();for(let i=1;i<times;i++)setTimeout(chime,i*1600);}
function tone(notes,type='sine'){
  if(!soundOn()||!audio)return;
  notes.forEach(([freq,delay])=>{const o=audio.createOscillator(),g=audio.createGain();o.type=type;o.frequency.value=freq;
    g.gain.setValueAtTime(.0001,audio.currentTime+delay);g.gain.exponentialRampToValueAtTime(.3,audio.currentTime+delay+.02);g.gain.exponentialRampToValueAtTime(.0001,audio.currentTime+delay+.3);
    o.connect(g).connect(audio.destination);o.start(audio.currentTime+delay);o.stop(audio.currentTime+delay+.35);});
}
// Avisos do MotoJá: compara o status de cada pedido com a última consulta e mostra (com som) o que mudou.
function motojaAlert(o){
  const m=o.motoja,who=m.motoboy?'O motoboy '+esc(m.motoboy):'Um motoboy',n='#'+o.number;
  const text={chamado:['ok','Pedido '+n+' enviado ao MotoJá','Deu certo! Agora é só aguardar um motoboy aceitar.'],
    na_fila:['ok','Pedido '+n+' chegou no MotoJá','Está aguardando a conferência no MotoJá para ir aos motoboys.'],
    aceito:['go','Motoboy a caminho!',who+' aceitou o pedido '+n+' e está vindo buscar.'],
    retirado:['go','Pedido '+n+' saiu para entrega',who+' já retirou o pedido.'],
    cancelado:['error','Corrida cancelada no MotoJá','Pedido '+n+': abra o pedido e chame o MotoJá de novo.'],
    erro:['error','Pedido '+n+' não foi enviado ao MotoJá',esc(m.message||'Abra o pedido e use Chamar MotoJá.')]}[m.status];
  if(!text)return;
  const [kind,title,body]=text;
  tone(kind==='error'?[[330,0],[262,.25]]:kind==='go'?[[660,0],[880,.15],[1320,.3]]:[[784,0],[1046,.16]],kind==='error'?'triangle':'sine');
  let box=$('#live-alerts');if(!box){box=document.createElement('div');box.id='live-alerts';box.setAttribute('aria-live','polite');document.body.appendChild(box);}
  const card=document.createElement('div');card.className='live-alert '+kind;card.setAttribute('role','status');
  card.innerHTML='<span class="live-alert-icon">'+icon('truck')+'</span><div><b>'+title+'</b><p>'+body+'</p><button type="button" class="link-btn" data-open>Ver pedido</button></div><button type="button" class="live-alert-close" aria-label="Fechar aviso">×</button>';
  box.prepend(card);[...box.children].slice(4).forEach(x=>x.remove());
  const close=()=>card.remove();
  card.querySelector('.live-alert-close').onclick=close;card.querySelector('[data-open]').onclick=()=>{close();orderDialog(o);};
  if(kind!=='error')setTimeout(close,15000);
  if('Notification' in window&&Notification.permission==='granted'&&document.hidden){try{new Notification(title,{body:body.replace(/<[^>]+>/g,''),icon:'/static/icon-192.png',tag:'motoja-'+o.id+'-'+m.status});}catch{}}
}
// Resposta nova do suporte: bolinha no menu, som e aviso (a tela de suporte aberta já mostra a mensagem).
let supportUnread=0;
function supportBadge(n){supportUnread=n;const b=$('[data-tab="support"]');if(!b)return;b.querySelector('.nav-count')?.remove();if(n)b.insertAdjacentHTML('beforeend','<span class="nav-count">'+n+'</span>');}
async function supportCheck(){
  if(tab==='support')return;
  const n=(await api('/api/admin/support/unread').catch(()=>({unread:supportUnread}))).unread;
  if(n>supportUnread){tone([[523,0],[659,.15],[784,.3]]);toast('O suporte respondeu sua mensagem. Abra Suporte para ver.');}
  supportBadge(n);
}
function motojaWatch(list){
  const now=new Map(list.filter(o=>o.motoja&&o.motoja.status).map(o=>[o.id,o.motoja.status]));
  let moved=false;
  if(motojaSeen)list.forEach(o=>{const s=now.get(o.id);if(s&&motojaSeen.get(o.id)!==s){moved=true;motojaAlert(o);}});
  motojaSeen=now;return moved;
}
function updateSoundButton(){const b=$('#sound-toggle');if(!b)return;b.classList.toggle('active',soundOn());b.setAttribute('aria-pressed',String(soundOn()));b.title=soundOn()?'Som de novos pedidos ligado':'Som de novos pedidos desligado';}
async function watchOrders(){
  if(watchBusy)return;watchBusy=true;
  clearTimeout(watchTimer);
  try{
    const active=(await api('/api/admin/orders?status=active')).orders,list=active.filter(o=>o.status==='new');
    setAlarm(list.filter(o=>!onlineMethod(o)||o.paid||o.total===0));
    const moved=motojaWatch(active);
    if(moved&&['overview','orders','drivers'].includes(tab))switchTab(tab,true);
    if(seen){const fresh=active.filter(o=>!seen.has(o.id)&&['new','preparing'].includes(o.status));if(fresh.length){
      if(!alarmTimer)ring(fresh.some(o=>o.status==='preparing')?4:1);const first=fresh[0];toast(fresh.length>1?fresh.length+' novos pedidos chegaram!':'Novo pedido #'+first.number+' • '+money(first.total));
      if('Notification' in window&&Notification.permission==='granted'&&document.hidden){try{new Notification('Novo pedido #'+first.number,{body:first.customer+' • '+money(first.total),icon:'/static/icon-192.png',tag:'pedido-'+first.id});}catch{}}
      if(['overview','orders','kitchen'].includes(tab))switchTab(tab,true);
    }}
    if(autoPrint()&&!(await refreshAgent()).active){
      try{
        const candidates=active.filter(o=>o.status==='preparing'&&(!onlineMethod(o)||o.paid||o.total===0));
        candidates.forEach(o=>{const what=autoPrintWhat(o);if(what)enqueuePrint(o,what);});
        if(printSeen)candidates.filter(o=>!printSeen.has(o.id)).slice().reverse().forEach(autoPrintTicket);
        else if(pendingPrints().length)toast('Há pendências de impressão. Abra Imprimir notinha e confira antes de repetir.');
        printSeen=new Set(candidates.map(o=>o.id));
      }catch{if(!journalWarning){journalWarning=true;toast('Não consegui guardar as pendências de impressão. Confira o armazenamento deste navegador.');}}
    }
    if(['owner','manager'].includes(role))operationNotices($('#operation-notices'),switchTab);
    supportCheck();
    seen=new Set(active.map(o=>o.id));document.title=(list.length?'('+list.length+') ':'')+'Painel • '+store.name;
  }catch(e){if(e.status===401){location.href='/entrar';return;}}finally{watchBusy=false;}
  watchTimer=setTimeout(watchOrders,alarmOrders.length?4000:15000);
}
function applyKioskPrinting(){
  try{const q=new URLSearchParams(location.search);if(q.get('impressao')==='automatica')localStorage.setItem('sca.kiosk-autoprint','1');
    const via=q.get('via')||localStorage.getItem('sca.kiosk-via');
    if(['tudo','balcao','cozinha'].includes(via)){localStorage.setItem('sca.kiosk-via',via);localStorage.setItem('sca.print-role',{tudo:'all',balcao:'counter',cozinha:'kitchen'}[via]);if(q.has('via')&&via==='cozinha')localStorage.setItem('sca.sound','0');}
    if(localStorage.getItem('sca.kiosk-autoprint')==='1'&&store){localStorage.setItem('sca.autoprint.'+store.id,'1');}
    if(q.has('impressao')||q.has('via')){q.delete('impressao');q.delete('via');history.replaceState(null,'',location.pathname+(q.toString()?'?'+q:''));}}catch{}
}
let agentState={active:false,last_seen:'',at:0};
async function refreshAgent(){if(Date.now()-agentState.at<60000)return agentState;try{agentState={...(await api('/api/admin/print-agent')),at:Date.now()};}catch{agentState={...agentState,at:Date.now()};}return agentState;}
const autoPrint=()=>{try{return (localStorage.getItem('sca.autoprint.'+store.id)??localStorage.getItem('sca.autoprint'))==='1';}catch{return false;}};
const b64=s=>{const p='='.repeat((4-s.length%4)%4);const raw=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));};
async function pushState(){
  if(!('serviceWorker' in navigator)||!('PushManager' in window))return 'unsupported';
  if(Notification.permission==='denied')return 'denied';
  const reg=await navigator.serviceWorker.getRegistration('/');const sub=reg&&await reg.pushManager.getSubscription();
  return sub?'on':'off';
}
async function enablePush(){
  if(!('serviceWorker' in navigator)||!('PushManager' in window))throw new Error('Este navegador não aceita avisos. No iPhone, adicione o painel à Tela de Início e abra por lá.');
  const permission=await Notification.requestPermission();
  if(permission!=='granted')throw new Error('Permita as notificações para este site nas configurações do navegador.');
  const reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});await navigator.serviceWorker.ready;
  const {public_key}=await api('/api/admin/push/key');
  let sub=await reg.pushManager.getSubscription();
  if(sub&&sub.options.applicationServerKey&&btoa(String.fromCharCode(...new Uint8Array(sub.options.applicationServerKey))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')!==public_key){await sub.unsubscribe();sub=null;}
  sub=sub||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64(public_key)});
  await api('/api/admin/push/subscribe',{method:'POST',body:JSON.stringify(sub.toJSON())});
}
async function disablePush(){
  const reg=await navigator.serviceWorker.getRegistration('/');const sub=reg&&await reg.pushManager.getSubscription();
  if(sub){await api('/api/admin/push/unsubscribe',{method:'POST',body:JSON.stringify({endpoint:sub.endpoint})}).catch(()=>{});await sub.unsubscribe();}
}
// Notinha da loja no formato de cupom de delivery: escolhas agrupadas e quanto cobrar do cliente.
function ticketChoices(extras){
  const groups=[],loose=[];
  extras.forEach(x=>{const name=String(x.name||''),cut=name.indexOf(': ');
    if(cut>0){const title=name.slice(0,cut).replace(/\s*\([^)]*\)\s*$/,''),option=name.slice(cut+2);let g=groups.find(y=>y.title===title);if(!g)groups.push(g={title,options:[]});const same=g.options.find(y=>y.name===option);same?same.n++:g.options.push({name:option,n:1});}
    else{const same=loose.find(y=>y.name===name);same?same.n++:loose.push({name,n:1});}});
  return groups.map(g=>'<div class="t-group">'+esc(g.title)+'</div>'+g.options.map(x=>'<div class="t-opt">'+x.n+' x '+esc(x.name)+'</div>').join('')).join('')+
    loose.map(x=>'<div class="t-opt">+ '+(x.n>1?x.n+' x ':'')+esc(x.name)+'</div>').join('');
}
const ticketPhone=v=>{const d=String(v||'').replace(/\D/g,'').replace(/^55(?=\d{10,11}$)/,'');return d.length===11?'('+d.slice(0,2)+') '+d.slice(2,7)+'-'+d.slice(7):d.length===10?'('+d.slice(0,2)+') '+d.slice(2,6)+'-'+d.slice(6):String(v||'');};
function ticketHTML(o){
  const line=(a,b,cls='')=>'<div class="t-line'+cls+'"><span>'+a+'</span><span>'+b+'</span></div>';
  const remaining=o.paid||o.payment==='credit'?0:(o.remaining_amount??o.total),received=o.paid?o.total:Math.max(0,o.total-remaining);
  const kind=o.source==='counter'&&o.mode!=='delivery'?'BALCÃO':o.mode==='delivery'?'DELIVERY - ENTREGA':'DELIVERY - RETIRADA BALCÃO';
  const when=new Date(o.created_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(',','');
  const printed=new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}).replace(',','');
  return '<div class="ticket t-receipt"><p class="t-center t-head">'+kind+'<br>'+esc(store.name.toLocaleUpperCase('pt-BR'))+'</p>'+
    (o.scheduled_for?'<p class="t-box t-center">AGENDADO: '+new Date(o.scheduled_for).toLocaleString('pt-BR',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+'</p>':'')+
    '<p class="t-order">Pedido Nº: '+o.number+' - '+when+'<br>'+esc(o.customer)+' '+esc(ticketPhone(o.phone))+(o.customer_orders?'<br>'+o.customer_orders+(o.customer_orders===1?' pedido':' pedidos'):'')+'</p>'+
    (o.mode==='delivery'?'<p class="t-box">ENTREGA'+(o.zone?' • '+esc(o.zone):'')+'<br>'+esc(o.address)+'</p>':'')+
    '<div class="t-cols"><span>PRODUTO</span><span>VENDA</span></div>'+
    o.items.map(i=>'<div class="t-product"><div class="t-line"><b>'+esc(i.name)+'</b><b>'+money(i.unit_price*i.quantity)+'</b></div><div>'+i.quantity+'x UN '+money(i.unit_price)+'</div>'+ticketChoices(i.extras)+(i.notes?'<div class="t-opt">OBS: '+esc(i.notes)+'</div>':'')+'</div>').join('')+
    (o.notes?'<p class="t-box">OBS. DO PEDIDO: '+esc(o.notes)+'</p>':'')+
    (o.delivery_fee||o.discount?'<div class="t-sums">'+line('Produtos',money(o.subtotal))+(o.delivery_fee?line('Entrega',money(o.delivery_fee)):'')+(o.discount?line('Desconto','- '+money(o.discount)):'')+'</div>':'')+
    line('Valor total',money(o.total),' t-total')+line('Valor pago',money(received))+line('Cobrar do cliente',money(remaining),' t-due')+
    '<p class="t-center t-pay">'+(pay[o.payment]||esc(o.payment))+(o.paid?' - JÁ PAGO':'')+(o.change_for&&!o.paid?'<br>Troco para '+money(o.change_for)+' (levar '+money(Math.max(0,o.change_for-remaining))+')':'')+'</p>'+
    '<p class="t-center t-foot">'+printed+'<br>SeuComércioAqui • documento não fiscal</p></div>';
}
// Via do motoboy: só o que ele precisa na rua, em letra grande, com QR code que abre o endereço no mapa.
function driverSlipHTML(o){
  const driver=drivers.find(x=>x.id===o.driver_id),volumes=o.items.reduce((n,i)=>n+i.quantity,0),change=o.change_for?o.change_for-(o.remaining_amount??o.total):0;
  return '<div class="ticket"><p class="t-tag">VIA DO MOTOBOY</p><h1>'+esc(store.name)+'</h1><p class="t-center t-big">PEDIDO #'+o.number+'</p>'+
    '<p class="t-big">'+esc(o.customer)+'<br>'+esc(o.phone)+'</p><p class="t-box t-big">'+(o.zone?esc(o.zone)+'<br>':'')+esc(o.address)+'</p>'+
    '<div class="t-qr"><img src="/api/admin/orders/'+o.id+'/map-qr" alt=""><span>Aponte a câmera do celular para abrir o endereço no mapa.</span></div><hr>'+
    (o.paid||o.payment==='credit'?'<p class="t-box t-center">'+(o.payment==='credit'&&!o.paid?'FIADO AUTORIZADO':'JÁ PAGO')+' • NÃO COBRAR</p>':'<p class="t-box t-center t-big">COBRAR '+money(o.remaining_amount??o.total)+'</p><p class="t-center">'+pay[o.payment]+(change>0?'<br>Cliente paga com '+money(o.change_for)+'<br><b>Levar troco: '+money(change)+'</b>':'')+'</p>')+
    '<p>'+volumes+(volumes===1?' item':' itens')+(driver?' • Entregador: '+esc(driver.name):'')+'</p>'+(o.notes?'<p><b>Obs.:</b> '+esc(o.notes)+'</p>':'')+'<p class="t-center t-foot">SeuComércioAqui</p></div>';
}
const pref=(k,d)=>{try{return localStorage.getItem('sca.'+k)??d;}catch{return d;}};
const setPref=(k,v)=>{try{localStorage.setItem('sca.'+k+(k==='autoprint'?'.'+store.id:''),v);}catch{}};
const printProfiles={'80':{label:'Bobina de 80 mm',width:72,max:76},'58':{label:'Bobina de 58 mm',width:48,max:50},'76':{label:'Bobina de 76 mm',width:68,max:68},'112':{label:'Bobina de 112 mm',width:104,max:104},a4:{label:'Folha A4',width:190,max:200},custom:{label:'Outra largura',width:72,max:200}};
const paperWidth=()=>Object.hasOwn(printProfiles,pref('paper','80'))?pref('paper','80'):'80';
const printContentWidth=()=>{const profile=printProfiles[paperWidth()],saved=Number(pref('print-width.'+paperWidth(),profile.width));return Number.isFinite(saved)&&saved>=32&&saved<=profile.max?saved:profile.width;};
const printFont=()=>{const saved=Number(pref('print-font',paperWidth()==='58'?11:12));return [11,12,14,16].includes(saved)?saved:12;};
function styleTicketArea(area,settings={paper:paperWidth(),width:printContentWidth(),font:printFont()}){
  area.className='paper-'+settings.paper;
  area.style.setProperty('--ticket-width',settings.width+'mm');
  area.style.setProperty('--ticket-font',settings.font+'px');
}
const driverCopy=()=>pref('driverslip','0')==='1';
// what: 'all' = notinha da loja (+ via do motoboy, se ligada e for entrega); 'driver' = só a via do motoboy.
const kitchenCopy=()=>pref('kitchenslip','1')==='1';
// Via da cozinha: só o que a produção precisa, em letra grande, com as escolhas agrupadas.
function kitchenSlipHTML(o,sector){
 const items=o.items.filter(i=>!sector||(i.production_sector||'Cozinha')===sector);if(!items.length)return '';
 const kind=o.source==='counter'&&o.mode!=='delivery'?'BALCÃO':o.mode==='delivery'?'DELIVERY - ENTREGA':'DELIVERY - RETIRADA BALCÃO';
 const printed=new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}).replace(',','');
 return '<div class="ticket t-receipt t-kitchen"><p class="t-center t-head">'+kind+(sector?' • '+esc(sector.toLocaleUpperCase('pt-BR')):' (COZINHA)')+'<br>'+esc(o.customer)+'<br>Pedido Nº: '+o.number+'<br>Impresso: '+printed+'</p>'+
   (o.scheduled_for?'<p class="t-box t-center">AGENDADO: '+new Date(o.scheduled_for).toLocaleString('pt-BR',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+'</p>':'')+
   '<div class="t-dots"></div>'+items.map(i=>'<div class="t-kitem">'+i.quantity+' x '+esc(i.name.toLocaleUpperCase('pt-BR'))+'</div>'+ticketChoices(i.extras)+(i.notes?'<p class="t-box">OBS: '+esc(i.notes)+'</p>':'')).join('')+
   (o.notes?'<p class="t-box">OBS. DO PEDIDO: '+esc(o.notes)+'</p>':'')+'<div class="t-dots"></div></div>';
}
const printRole=()=>{const v=pref('print-role','all');return ['all','counter','kitchen'].includes(v)?v:'all';};
// Qual via esta janela imprime sozinha: setor de produção, só cozinha, só balcão ou tudo. null = não imprime este pedido.
function autoPrintWhat(o){
  const sector=printSector();if(sector)return o.items.some(i=>(i.production_sector||'Cozinha')===sector)?'sector:'+sector:null;
  return {kitchen:'kitchen',counter:'counter'}[printRole()]||'all';
}
const printSector=()=>{try{return localStorage.getItem('sca.print-sector.'+store.id)||'';}catch{return '';}};
function autoPrintTicket(o){const what=autoPrintWhat(o);if(what)printTicket(o,what,false,true);}
function printJobHTML(o,what='all'){
  const sector=typeof what==='string'&&what.startsWith('sector:')?what.slice(7):null;
  const slip=sector===null&&o.mode==='delivery'&&(what==='driver'||driverCopy());
  if(sector!==null)return kitchenSlipHTML(o,sector);
  if(what==='driver')return driverSlipHTML(o);
  if(what==='kitchen')return kitchenSlipHTML(o,null);
  const kitchen=what!=='counter'&&kitchenCopy()?kitchenSlipHTML(o,null):'';
  return ticketHTML(o)+(kitchen?'<div class="t-cut"></div>'+kitchen:'')+(slip?'<div class="t-cut"></div>'+driverSlipHTML(o):'');
}
function calibrationHTML(){return '<div class="t-calibration"><b>TESTE DE IMPRESSÃO</b><p>Acentos: pão, ação, açúcar, café.<br>Valores: R$ 12,34 • 2 × produto.</p><div class="t-ruler">20 mm</div><p>Confira a linha com uma régua. Se cortar texto, reduza a área útil; se a linha mudar de tamanho, confira a escala de 100% no navegador.</p></div>';}
function printTicket(o,what='all',calibration=false,automatic=false){
  const html=printJobHTML(o,what)+(calibration?calibrationHTML():'');
  const settings={paper:paperWidth(),width:printContentWidth(),font:printFont()};
  return o.id?trackedPrint(o,what,()=>printDocument(html,settings),automatic):printDocument(html,settings);
}
const sampleOrder=()=>({id:0,number:123,created_at:new Date().toISOString(),customer:'Cliente Teste',phone:'(19) 99999-0000',mode:'delivery',zone:'Centro',address:store.address||'Rua Exemplo, 100 - Centro',
  items:[{quantity:2,name:'Produto de teste com nome comprido',unit_price:2500,extras:[{name:'Adicional: queijo e açúcar à parte'}],notes:'Sem cebola. Embalar separadamente.'}],notes:'Notinha de teste • confira se o texto está completo.',subtotal:5000,delivery_fee:500,discount:0,total:5500,payment:'cash',paid:false,change_for:10000});
function previewTicket(){
  modal('Prévia da notinha','<p class="muted">'+esc(printProfiles[paperWidth()].label)+' • área útil de '+printContentWidth()+' mm. A impressora é escolhida na janela do navegador.</p><div class="print-preview-scroll"><div id="print-preview-sheet">'+printJobHTML(sampleOrder())+calibrationHTML()+'</div></div><button type="button" class="btn full" id="print-preview-test">'+icon('print')+' Imprimir este teste</button>',true);
  styleTicketArea($('#print-preview-sheet'));
  $('#print-preview-test').onclick=()=>{closeModal();printTicket(sampleOrder(),'all',true);};
}
function alertsPanel(){
  return '<section class="panel" id="alerts-panel"><div class="section-heading"><div><h2>Avisos neste aparelho</h2><p class="muted">Valem para este celular ou computador. Ative em cada aparelho que recebe pedidos.</p></div><span class="feature-icon">'+icon('bell')+'</span></div>'+
    '<div class="alert-row"><div><b>Aviso de pedido novo, mesmo com o painel fechado</b><p class="muted" id="push-status">Verificando…</p></div><div class="row-actions"><button type="button" class="btn" id="push-toggle">Ativar avisos</button><button type="button" class="btn secondary" id="push-test" hidden>Testar</button></div></div>'+
    '<div class="alert-row"><div><b>Impressora de notinha</b><p class="muted">A impressão agora tem uma página só dela no menu.</p></div><button type="button" class="btn secondary" data-goto="printing">'+icon('print')+' Imprimir notinha</button></div></section>';
}
// Configurador do Windows: escolhe a impressora pelo nome e grava como destino do Chrome de impressão (perfil separado).
function printerInstaller(pattern,startup,kitchenPattern=''){
  const ps=s=>String(s).replace(/'/g,"''");
  const url=location.origin+'/painel?impressao=automatica';
  const code=[
    "$ErrorActionPreference='Stop'",
    "$Pattern='"+ps(pattern)+"'","$KitchenPattern='"+ps(kitchenPattern)+"'","$Two="+(kitchenPattern?'$true':'$false'),
    "$Url='"+ps(url)+"'","$Startup="+(startup?'$true':'$false'),
    "Write-Host ''","Write-Host 'SeuComercioAqui - configurar impressao automatica da notinha' -ForegroundColor Green","Write-Host ''",
    "$printers=@(Get-Printer | Select-Object -ExpandProperty Name | Sort-Object)",
    "if($printers.Count -eq 0){Write-Host 'Nenhuma impressora instalada. Instale o driver da impressora de notinha e rode de novo.' -ForegroundColor Red; exit 1}",
    "function Pick($pat,$label,$skip){",
    "  $list=@($printers | Where-Object { $_ -ne $skip })",
    "  if($list.Count -eq 0){Write-Host 'Nao sobrou outra impressora para escolher.' -ForegroundColor Red; exit 1}",
    "  $match=@($list | Where-Object { $pat -and $_ -like ($pat+'*') })",
    "  if($match.Count -eq 0){$match=@($list | Where-Object { $pat -and $_ -like ('*'+$pat+'*') })}",
    "  if($match.Count -eq 1){Write-Host ('Impressora '+$label+': '+$match[0]) -ForegroundColor Green; return $match[0]}",
    "  if($match.Count -gt 1){Write-Host ('Achei mais de uma impressora com '+$pat+'.') -ForegroundColor Yellow} else {Write-Host ('Nao achei impressora que comece com '+$pat+'.') -ForegroundColor Yellow}",
    "  Write-Host ('Escolha a impressora '+$label+':')",
    "  for($i=0;$i -lt $list.Count;$i++){Write-Host ('  '+($i+1)+' - '+$list[$i])}",
    "  do{$n=Read-Host 'Digite o numero e aperte Enter'}until($n -match '^[0-9]+$' -and [int]$n -ge 1 -and [int]$n -le $list.Count)",
    "  $chosen=$list[[int]$n-1]; Write-Host ('Impressora '+$label+': '+$chosen) -ForegroundColor Green; return $chosen",
    "}",
    "$roots=@($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA) | Where-Object { $_ }",
    "$browsers=@(foreach($r in $roots){(Join-Path $r 'Google\\Chrome\\Application\\chrome.exe')}; foreach($r in $roots){(Join-Path $r 'Microsoft\\Edge\\Application\\msedge.exe')})",
    "$browser=$browsers | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1",
    "if(-not $browser){Write-Host 'Nao achei o Google Chrome nem o Microsoft Edge. Instale o Chrome e rode de novo.' -ForegroundColor Red; exit 1}",
    "$shell=New-Object -ComObject WScript.Shell",
    "$places=@([Environment]::GetFolderPath('Desktop')); if($Startup){$places+=[Environment]::GetFolderPath('Startup')}",
    "function Setup($printer,$folder,$via,$name){",
    "  $dir=Join-Path $env:LOCALAPPDATA ('SeuComercioAqui\\'+$folder)",
    "  $def=Join-Path $dir 'Default'",
    "  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like ('*'+$dir+'*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
    "  Start-Sleep -Seconds 1",
    "  New-Item -ItemType Directory -Force -Path $def | Out-Null",
    "  $file=Join-Path $def 'Preferences'",
    "  $prefs=$null; if(Test-Path $file){try{$prefs=Get-Content -Raw -LiteralPath $file | ConvertFrom-Json}catch{$prefs=$null}}",
    "  if(-not $prefs){$prefs=New-Object PSObject}",
    "  $dest=[ordered]@{id=$printer;origin='local';account='';capabilities='';displayName=$printer;extensionId='';extensionName=''}",
    "  $state=[ordered]@{version=2;recentDestinations=@($dest);isHeaderFooterEnabled=$false;marginsType=0;scaling='100';scalingType=0;isCssBackgroundEnabled=$true}",
    "  $appState=ConvertTo-Json -InputObject $state -Compress -Depth 6",
    "  if(-not $prefs.PSObject.Properties['printing']){$prefs | Add-Member -NotePropertyName printing -NotePropertyValue (New-Object PSObject)}",
    "  $prefs.printing | Add-Member -NotePropertyName print_preview_sticky_settings -NotePropertyValue ([pscustomobject]@{appState=$appState}) -Force",
    "  if(-not $prefs.PSObject.Properties['browser']){$prefs | Add-Member -NotePropertyName browser -NotePropertyValue (New-Object PSObject)}",
    "  $prefs.browser | Add-Member -NotePropertyName has_seen_welcome_page -NotePropertyValue $true -Force",
    "  [IO.File]::WriteAllText($file,(ConvertTo-Json -InputObject $prefs -Compress -Depth 60),(New-Object Text.UTF8Encoding $false))",
    "  $flags='--kiosk-printing --user-data-dir=\"'+$dir+'\" --no-first-run --no-default-browser-check \"'+$Url+'&via='+$via+'\"'",
    "  foreach($place in $places){$link=$shell.CreateShortcut((Join-Path $place ($name+'.lnk')));$link.TargetPath=$browser;$link.Arguments=$flags;$link.IconLocation=$browser+',0';$link.Description='Painel do SeuComercioAqui com impressao automatica';$link.Save()}",
    "  return $flags",
    "}",
    "if($Two){",
    "  $counter=Pick $Pattern 'do BALCAO (notinha do cliente)' ''",
    "  $kitchen=Pick $KitchenPattern 'da COZINHA' $counter",
    "  $f1=Setup $counter 'ImpressaoBalcao' 'balcao' 'Painel de pedidos'",
    "  $f2=Setup $kitchen 'ImpressaoCozinha' 'cozinha' 'Painel da cozinha'",
    "  Write-Host ''","  Write-Host 'Pronto! Criei os atalhos Painel de pedidos (balcao) e Painel da cozinha na Area de Trabalho.' -ForegroundColor Green",
    "  Write-Host 'Vou abrir as duas janelas: entre com seu e-mail e senha em cada uma e clique em Imprimir notinha > Imprimir teste.'",
    "  Write-Host ('Balcao: '+$counter+'  |  Cozinha: '+$kitchen)",
    "  Start-Process -FilePath $browser -ArgumentList $f1; Start-Sleep -Seconds 2; Start-Process -FilePath $browser -ArgumentList $f2",
    "} else {",
    "  $printer=Pick $Pattern 'de NOTINHA (nao a de folha A4)' ''",
    "  $f=Setup $printer 'ImpressaoAutomatica' 'tudo' 'Painel de pedidos'",
    "  Write-Host ''","  Write-Host 'Pronto! Criei o atalho Painel de pedidos na Area de Trabalho.' -ForegroundColor Green",
    "  Write-Host 'Vou abrir o painel: entre com seu e-mail e senha e clique em Imprimir notinha > Imprimir teste.'",
    "  Write-Host ('As duas notinhas (cliente e cozinha) devem sair na '+$printer+' sem perguntar.')",
    "  Start-Process -FilePath $browser -ArgumentList $f",
    "}"
  ].join('\r\n');
  return '@echo off\r\ntitle Configurar impressora de notinha - SeuComercioAqui\r\npowershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText(\'%~f0\');iex ($t.Substring($t.LastIndexOf([string][char]35+\'PS\'+[char]35)+4))"\r\necho.\r\npause\r\nexit /b\r\n#PS#\r\n'+code+'\r\n';
}
async function bindPrintAgent(){
  const status=$('#agent-status');
  const draw=async()=>{agentState.at=0;const st=await refreshAgent();if(!status.isConnected)return;status.className='agent-status '+(st.active?'on':'off');
    status.textContent=st.active?'Agente ligado: os pedidos aceitos saem sozinhos (último contato '+new Date(st.last_seen).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})+'). O navegador não imprime para não sair em dobro.':st.last_seen?'Agente desligado ou sem internet desde '+new Date(st.last_seen).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+'. Ligue o computador da impressora.':'Nenhum agente instalado ainda.';};
  draw();
  $$('[name=agent-count]').forEach(r=>r.onchange=()=>{const two=r.value==='2'&&r.checked;setPref('printer-count',two?'2':'1');$('#agent-kitchen-field').hidden=!two;$('#agent-pattern-label').textContent=two?'Impressora do balcão começa com':'A impressora de notinha começa com';});
  $('#download-agent').onclick=async e=>{
    const button=e.currentTarget,pattern=$('#agent-pattern').value.trim()||'MP-',kitchen=$('#agent-pattern-kitchen').value.trim(),two=$('[name=agent-count][value="2"]').checked;
    if(two&&!kitchen){toast('Informe o começo do nome da impressora da cozinha.');$('#agent-pattern-kitchen').focus();return;}
    setPref('printer-pattern',pattern);setPref('printer-pattern-kitchen',kitchen);setPref('printer-count',two?'2':'1');setPref('kitchenslip',$('#agent-kitchen-copy').checked?'1':'0');
    button.disabled=true;
    try{
      const old=(await api('/api/admin/integrations')).keys.filter(k=>!k.revoked_at&&String(k.name).startsWith('Agente de impressão'));
      const stamp=new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
      const {token}=await api('/api/admin/integrations/keys',{method:'POST',body:JSON.stringify({name:'Agente de impressão '+stamp,scopes:['print:jobs']})});
      for(const k of old)await api('/api/admin/integrations/keys/'+k.id,{method:'DELETE'}).catch(()=>{});
      const blob=new Blob([agentInstaller({token,pattern,kitchen:two?kitchen:'',cols:Number($('#agent-paper').value),kitchenCopy:$('#agent-kitchen-copy').checked})],{type:'application/octet-stream'});
      const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='Instalar-agente-impressao.bat';document.body.append(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);
      toast('Agente baixado. Abra o arquivo no computador da impressora.');
    }catch(err){toast(err.message);}finally{button.disabled=false;}
  };
}
// Agente do Windows: PowerShell que imprime direto pela impressora (System.Drawing), sem navegador. Só ASCII no código.
function agentScript(){
  return [
    "$ErrorActionPreference='Stop'",
    "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12",
    "Add-Type -AssemblyName System.Drawing",
    "function Send-ToPrinter($printer,$lines){",
    "  $doc=New-Object System.Drawing.Printing.PrintDocument",
    "  $doc.PrinterSettings.PrinterName=$printer",
    "  if(-not $doc.PrinterSettings.IsValid){throw ('Impressora nao encontrada: '+$printer)}",
    "  $doc.DocumentName='SeuComercioAqui'",
    "  $doc.DefaultPageSettings.Margins=New-Object System.Drawing.Printing.Margins(6,6,6,6)",
    "  $script:queue=@($lines); $script:pos=0",
    "  $doc.add_PrintPage({",
    "    param($s,$e)",
    "    $g=$e.Graphics; $area=$e.MarginBounds; $size=11.0",
    "    while($size -gt 5){$f=New-Object System.Drawing.Font('Consolas',[single]$size); $w=$g.MeasureString(('M'*$script:Cols),$f).Width; $f.Dispose(); if($w -le $area.Width){break}; $size-=0.5}",
    "    $y=[single]$area.Top",
    "    while($script:pos -lt $script:queue.Count){",
    "      $l=$script:queue[$script:pos]",
    "      $style=[System.Drawing.FontStyle]::Regular; if($l.b){$style=[System.Drawing.FontStyle]::Bold}",
    "      $fs=$size; if($l.s){$fs=$size*1.4}",
    "      $font=New-Object System.Drawing.Font('Consolas',[single]$fs,$style)",
    "      $h=$font.GetHeight($g)",
    "      if(($y+$h) -gt $area.Bottom -and $y -gt $area.Top){$font.Dispose(); $e.HasMorePages=$true; return}",
    "      $text=[string]$l.t; $x=[single]$area.Left",
    "      if($l.c){$text=$text.Trim(); $tw=$g.MeasureString($text,$font).Width; $x=[single]($area.Left+[Math]::Max(0,($area.Width-$tw)/2))}",
    "      $g.DrawString($text,$font,[System.Drawing.Brushes]::Black,$x,$y)",
    "      $y+=$h; $font.Dispose(); $script:pos++",
    "    }",
    "    $e.HasMorePages=$false",
    "  })",
    "  $doc.Print(); $doc.Dispose()",
    "}",
    "function Line($t,$b,$c,$big){[pscustomobject]@{t=$t;b=$b;c=$c;s=$big}}",
    "#LOOP#",
    "$Dir=Split-Path -Parent $MyInvocation.MyCommand.Path",
    "$Log=Join-Path $Dir 'agente-impressao.log'",
    "function Write-Log($m){try{Add-Content -LiteralPath $Log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss')+' '+$m)}catch{}}",
    "$created=$false; $mutex=New-Object System.Threading.Mutex($true,'SeuComercioAquiAgenteImpressao',[ref]$created)",
    "if(-not $created){exit}",
    "Write-Log 'Agente iniciado'",
    "$headers=@{Authorization=('Bearer '+$Key)}",
    "$done=@{}",
    "while($true){",
    "  try{",
    "    $r=Invoke-RestMethod -Uri ($Server+'/api/v1/print/jobs?cols='+$Cols) -Headers $headers -TimeoutSec 25",
    "    foreach($j in @($r.jobs)){",
    "      try{",
    "        if(-not $done.ContainsKey([string]$j.id)){",
    "          Send-ToPrinter $Counter $j.counter",
    "          if($KitchenCopy){$kp=$Counter; if($Kitchen){$kp=$Kitchen}; Send-ToPrinter $kp $j.kitchen}",
    "          $done[[string]$j.id]=$true",
    "          Write-Log ('Pedido '+$j.number+' impresso')",
    "        }",
    "        Invoke-RestMethod -Method Post -Uri ($Server+'/api/v1/print/jobs/'+$j.id+'/done') -Headers $headers -TimeoutSec 25 | Out-Null",
    "      }catch{Write-Log ('Erro no pedido '+$j.number+': '+$_.Exception.Message); Start-Sleep -Seconds 10}",
    "    }",
    "  }catch{Write-Log ('Sem conexao: '+$_.Exception.Message); Start-Sleep -Seconds 10}",
    "  Start-Sleep -Seconds 4",
    "}"
  ].join('\r\n');
}
function agentInstaller({token,pattern,kitchen,cols,kitchenCopy}){
  const ps=s=>String(s).replace(/'/g,"''");
  const b64=t=>btoa(String.fromCharCode(...new TextEncoder().encode(t)));
  const code=[
    "$ErrorActionPreference='Stop'",
    "$Server='"+ps(location.origin)+"'","$Key='"+ps(token)+"'","$Pattern='"+ps(pattern)+"'","$KitchenPattern='"+ps(kitchen)+"'",
    "$Cols="+Number(cols),"$KitchenCopy="+(kitchenCopy?'$true':'$false'),
    "$Agent=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+b64(agentScript())+"'))",
    "Write-Host ''","Write-Host 'SeuComercioAqui - instalar o agente de impressao' -ForegroundColor Green","Write-Host ''",
    "$printers=@(Get-Printer | Select-Object -ExpandProperty Name | Sort-Object)",
    "if($printers.Count -eq 0){Write-Host 'Nenhuma impressora instalada. Instale o driver da impressora de notinha e rode de novo.' -ForegroundColor Red; exit 1}",
    "function Pick($pat,$label,$skip){",
    "  $list=@($printers | Where-Object { $_ -ne $skip })",
    "  if($list.Count -eq 0){Write-Host 'Nao sobrou outra impressora para escolher.' -ForegroundColor Red; exit 1}",
    "  $match=@($list | Where-Object { $pat -and $_ -like ($pat+'*') })",
    "  if($match.Count -eq 0){$match=@($list | Where-Object { $pat -and $_ -like ('*'+$pat+'*') })}",
    "  if($match.Count -eq 1){Write-Host ('Impressora '+$label+': '+$match[0]) -ForegroundColor Green; return $match[0]}",
    "  if($match.Count -gt 1){Write-Host ('Achei mais de uma impressora com '+$pat+'.') -ForegroundColor Yellow} else {Write-Host ('Nao achei impressora que comece com '+$pat+'.') -ForegroundColor Yellow}",
    "  Write-Host ('Escolha a impressora '+$label+':')",
    "  for($i=0;$i -lt $list.Count;$i++){Write-Host ('  '+($i+1)+' - '+$list[$i])}",
    "  do{$n=Read-Host 'Digite o numero e aperte Enter'}until($n -match '^[0-9]+$' -and [int]$n -ge 1 -and [int]$n -le $list.Count)",
    "  $chosen=$list[[int]$n-1]; Write-Host ('Impressora '+$label+': '+$chosen) -ForegroundColor Green; return $chosen",
    "}",
    "if($KitchenPattern){$Counter=Pick $Pattern 'do BALCAO (notinha do cliente)' ''; $Kitchen=Pick $KitchenPattern 'da COZINHA' $Counter} else {$Counter=Pick $Pattern 'de NOTINHA (nao a de folha A4)' ''; $Kitchen=''}",
    "$Functions=$Agent.Substring(0,$Agent.IndexOf('#LOOP#'))",
    "Invoke-Expression $Functions",
    "Write-Host 'Imprimindo um teste...'",
    "$test=@((Line 'TESTE DE IMPRESSAO' $true $true $true),(Line 'SeuComercioAqui' $true $true $false),(Line ('-'*$Cols) $false $false $false),(Line 'Se esta notinha saiu aqui, a impressora esta certa.' $false $false $false),(Line 'Os pedidos aceitos vao sair sozinhos.' $false $false $false),(Line ('-'*$Cols) $false $false $false))",
    "try{Send-ToPrinter $Counter $test; if($Kitchen){Send-ToPrinter $Kitchen @((Line 'TESTE - COZINHA' $true $true $true),(Line ('-'*$Cols) $false $false $false))}}catch{Write-Host ('Nao consegui imprimir o teste: '+$_.Exception.Message) -ForegroundColor Red; exit 1}",
    "$dir=Join-Path $env:LOCALAPPDATA 'SeuComercioAqui'",
    "New-Item -ItemType Directory -Force -Path $dir | Out-Null",
    "$file=Join-Path $dir 'agente-impressao.ps1'",
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like '*agente-impressao.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
    "Start-Sleep -Seconds 1",
    "$config=\"`$Server='\"+$Server.Replace(\"'\",\"''\")+\"'`r`n`$Key='\"+$Key+\"'`r`n`$Counter='\"+$Counter.Replace(\"'\",\"''\")+\"'`r`n`$Kitchen='\"+$Kitchen.Replace(\"'\",\"''\")+\"'`r`n`$Cols=\"+$Cols+\"`r`n`$KitchenCopy=`$\"+$KitchenCopy.ToString().ToLower()+\"`r`n\"",
    "[IO.File]::WriteAllText($file,($config+$Agent),(New-Object Text.UTF8Encoding $true))",
    "$ps=Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'",
    "$args2='-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"'+$file+'\"'",
    "$shell=New-Object -ComObject WScript.Shell",
    "$link=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'SeuComercioAqui - agente de impressao.lnk')); $link.TargetPath=$ps; $link.Arguments=$args2; $link.WindowStyle=7; $link.Description='Imprime os pedidos do SeuComercioAqui'; $link.Save()",
    "Start-Process -FilePath $ps -ArgumentList $args2 -WindowStyle Hidden",
    "Write-Host ''","Write-Host 'Pronto! O agente de impressao esta ligado e vai ligar sozinho com o Windows.' -ForegroundColor Green",
    "Write-Host 'Cada pedido aceito vai sair sozinho na impressora, sem abrir janela. Pode fechar esta tela.'"
  ].join('\r\n');
  return '@echo off\r\ntitle Instalar agente de impressao - SeuComercioAqui\r\npowershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText(\'%~f0\');iex ($t.Substring($t.LastIndexOf([string][char]35+\'PS\'+[char]35)+4))"\r\necho.\r\npause\r\nexit /b\r\n#PS#\r\n'+code+'\r\n';
}
function printPanel(){
  const chromeCmd='"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --kiosk-printing '+location.origin+'/painel';
  const settings='<section class="panel print-settings-panel" id="print-panel"><div class="section-heading"><div><span class="eyebrow">DO SEU JEITO</span><h2>Impressora de notinha</h2><p class="muted">Preferências salvas neste navegador.</p></div><span class="feature-icon">'+icon('gear')+'</span></div>'+
    '<div class="alert-row"><div><b>Imprimir automaticamente cada pedido novo</b><p class="muted">A notinha sai assim que o pedido é aceito (vai para preparo), com o painel aberto. Veja abaixo como imprimir sem a janela de confirmação.</p></div><label class="switch"><input type="checkbox" id="autoprint" '+(autoPrint()?'checked':'')+'><span>'+(autoPrint()?'Ligado':'Desligado')+'</span></label></div>'+
    '<div class="alert-row"><div><b>Este computador imprime</b><p class="muted">Com uma impressora, deixe tudo nela. Com duas, a janela do balcão imprime a notinha do cliente e a janela da cozinha imprime só a via da cozinha (o configurador abaixo já deixa cada uma certa).</p></div><select id="print-role" aria-label="O que este computador imprime"><option value="all" '+(printRole()==='all'?'selected':'')+'>Tudo: cliente e cozinha</option><option value="counter" '+(printRole()==='counter'?'selected':'')+'>Só a notinha do balcão (cliente)</option><option value="kitchen" '+(printRole()==='kitchen'?'selected':'')+'>Só a via da cozinha</option></select></div>'+
    '<div class="alert-row"><div><b>Setor neste aparelho</b><p class="muted">Deixe vazio para a notinha completa. Informe o mesmo setor do cadastro dos produtos para imprimir apenas a produção desse setor.</p></div><input id="print-sector" aria-label="Setor de impressão automática" maxlength="60" value="'+esc(printSector())+'" placeholder="Ex.: Cozinha ou Bar"></div>'+
    '<div class="alert-row"><div><b>Papel da impressora</b><p class="muted">Escolha o mesmo tamanho configurado no driver do Windows. Para outro tamanho, use Outra largura e ajuste a área útil abaixo.</p></div><select id="paper-width" aria-label="Largura do papel">'+Object.entries(printProfiles).map(([key,p])=>'<option value="'+key+'" '+(paperWidth()===key?'selected':'')+'>'+p.label+'</option>').join('')+'</select></div>'+
    '<div class="alert-row"><div><b>Área útil de impressão</b><p class="muted">Largura ocupada pelo texto em milímetros. Se cortar nas laterais, reduza este valor e imprima outro teste.</p></div><label class="print-number"><input type="number" id="print-content-width" aria-label="Área útil de impressão em milímetros" min="32" max="'+printProfiles[paperWidth()].max+'" step="0.5" value="'+printContentWidth()+'"><span>mm</span></label></div>'+
    '<div class="alert-row"><div><b>Tamanho das letras</b><p class="muted">Aumente para facilitar a leitura ou diminua para caber mais conteúdo.</p></div><select id="print-font" aria-label="Tamanho das letras na notinha">'+[[11,'Pequena'],[12,'Padrão'],[14,'Grande'],[16,'Muito grande']].map(([size,label])=>'<option value="'+size+'" '+(printFont()===size?'selected':'')+'>'+label+'</option>').join('')+'</select></div>'+
    '<div class="alert-row"><div><b>Via da cozinha</b><p class="muted">Junto com a notinha do cliente sai uma segunda, só com os itens e as escolhas em letra grande, para quem prepara.</p></div><label class="switch"><input type="checkbox" id="kitchenslip" '+(kitchenCopy()?'checked':'')+'><span>'+(kitchenCopy()?'Ligado':'Desligado')+'</span></label></div>'+
    '<div class="alert-row"><div><b>Via do motoboy</b><p class="muted">Nos pedidos de entrega, sai uma segunda notinha com o endereço em letra grande, QR code do mapa e quanto cobrar (com o troco).</p></div><label class="switch"><input type="checkbox" id="driverslip" '+(driverCopy()?'checked':'')+'><span>'+(driverCopy()?'Ligado':'Desligado')+'</span></label></div>'+
    '</section>';
  const cols=paperWidth()==='58'?32:42,agentTwo=pref('printer-count','1')==='2';
  const agent='<section class="panel print-installer print-agent" id="print-agent"><div class="section-heading"><div><span class="eyebrow">RECOMENDADO • SEM JANELA, SEM CLIQUE</span><h2>Agente de impressão</h2><p class="muted">Um programinha para o Windows do caixa, como o do Beefood: fica ligado escondido, pega cada pedido aceito e imprime na hora, direto na impressora escolhida pelo nome. Funciona mesmo com o painel fechado. A impressora padrão e a de folha A4 não são usadas.</p></div><span class="feature-icon">'+icon('print')+'</span></div>'+
    '<p class="agent-status" id="agent-status">Verificando o agente…</p>'+
    '<div class="choice-row printer-count" role="radiogroup" aria-label="Quantas impressoras de notinha"><label><input type="radio" name="agent-count" value="1" '+(agentTwo?'':'checked')+'> Uma impressora: sai a notinha do cliente e a da cozinha nela</label><label><input type="radio" name="agent-count" value="2" '+(agentTwo?'checked':'')+'> Duas impressoras: cliente no balcão e cozinha na cozinha</label></div>'+
    '<div class="form-grid"><label><span id="agent-pattern-label">'+(agentTwo?'Impressora do balcão começa com':'A impressora de notinha começa com')+'</span><input id="agent-pattern" maxlength="40" value="'+esc(pref('printer-pattern','MP-'))+'" placeholder="Ex.: MP-, ELGIN, EPSON TM"></label><label id="agent-kitchen-field" '+(agentTwo?'':'hidden')+'>Impressora da cozinha começa com<input id="agent-pattern-kitchen" maxlength="40" value="'+esc(pref('printer-pattern-kitchen',''))+'" placeholder="Ex.: ELGIN i9"></label></div>'+
    '<div class="form-grid"><label>Papel<select id="agent-paper"><option value="42" '+(cols===42?'selected':'')+'>Bobina de 80 mm</option><option value="32" '+(cols===32?'selected':'')+'>Bobina de 58 mm</option></select></label><label class="check-row installer-startup"><span><input type="checkbox" id="agent-kitchen-copy" '+(kitchenCopy()?'checked':'')+'> Imprimir também a via da cozinha</span></label></div>'+
    '<ol class="steps"><li>Clique em <b>Baixar agente de impressão</b> no computador da impressora e abra o arquivo (se o Windows avisar: <b>Mais informações → Executar assim mesmo</b>).</li><li>Se o nome não bater com uma impressora só, escolha pelo número a de <b>notinha</b>, não a de folha.</li><li>Ele imprime um <b>teste</b> na hora. Saiu na impressora certa? Pronto: daí em diante cada pedido aceito sai sozinho, e o agente liga junto com o Windows.</li></ol>'+
    '<button type="button" class="btn" id="download-agent">'+icon('print')+' Baixar agente de impressão</button><p class="muted small">O arquivo leva uma chave que só serve para imprimir pedidos desta loja. Baixar de novo troca a chave e desliga o agente antigo.</p></section>';
  const two=pref('printer-count','1')==='2';
  const installer='<section class="panel print-installer" id="print-installer"><div class="section-heading"><div><span class="eyebrow">ALTERNATIVA PELO NAVEGADOR</span><h2>Atalho do Chrome que imprime sem perguntar</h2><p class="muted">Escolha quantas impressoras de notinha este computador tem e o começo do nome de cada uma. O configurador acha cada impressora e cria um atalho preso a ela, que imprime direto, sem perguntar. A impressora padrão do Windows, a de folha A4 e o Chrome normal não mudam.</p></div><span class="feature-icon">'+icon('print')+'</span></div>'+
    '<div class="choice-row printer-count" role="radiogroup" aria-label="Quantas impressoras de notinha"><label><input type="radio" name="printer-count" value="1" '+(two?'':'checked')+'> Uma impressora: sai a notinha do cliente e a da cozinha nela</label><label><input type="radio" name="printer-count" value="2" '+(two?'checked':'')+'> Duas impressoras: cliente no balcão e cozinha na cozinha</label></div>'+
    '<div class="form-grid"><label><span id="printer-pattern-label">'+(two?'Impressora do balcão começa com':'A impressora de notinha começa com')+'</span><input id="printer-pattern" maxlength="40" value="'+esc(pref('printer-pattern','MP-'))+'" placeholder="Ex.: MP-, ELGIN, EPSON TM"></label><label id="kitchen-pattern-field" '+(two?'':'hidden')+'>Impressora da cozinha começa com<input id="printer-pattern-kitchen" maxlength="40" value="'+esc(pref('printer-pattern-kitchen',''))+'" placeholder="Ex.: ELGIN i9"></label></div>'+
    '<label class="check-row installer-startup"><span><input type="checkbox" id="printer-startup" checked> Abrir o painel sozinho quando ligar o computador</span></label>'+
    '<ol class="steps"><li>Clique em <b>Baixar configurador</b> e abra o arquivo baixado (se o Windows avisar, clique em <b>Mais informações → Executar assim mesmo</b>).</li><li>Se o nome não bater com uma impressora só, ele mostra a lista para escolher pelo número. Escolha a de <b>notinha</b>, não a de folha.</li><li>Com uma impressora, abre o atalho <b>Painel de pedidos</b>. Com duas, abre também o <b>Painel da cozinha</b>. Entre com seu e-mail e senha em cada janela uma vez e clique em <b>Imprimir teste</b>.</li><li>Deixe as janelas abertas para receber pedidos. Elas abrem sozinhas quando o computador liga.</li></ol>'+
    '<button type="button" class="btn" id="download-installer">'+icon('print')+' Baixar configurador</button></section>';
  const help='<section class="panel print-help-panel">'+
    '<details class="help print-help"><summary>Como configurar a impressora de notinha</summary>'+
      '<h3>Windows: qualquer marca com driver de impressão compatível</h3><ol><li>Instale o driver oficial do seu modelo. Em <b>Configurações do Windows → Impressoras e scanners</b>, confirme se a impressora aparece e imprime a página de teste do Windows. Se usar USB, prefira o driver de impressão do Windows; apenas instalar uma porta COM virtual pode não criar uma impressora na lista.</li><li>Configure no driver o tamanho real da bobina ou A4. Aqui, selecione o mesmo tamanho e clique em <b>Imprimir teste</b>. No Chrome ou Edge, escolha a impressora em <b>Destino</b>, use <b>escala 100%</b>, orientação retrato e desative <b>Cabeçalhos e rodapés</b>. Use margens mínimas ou nenhuma, conforme o driver. Se cortar nas laterais, reduza a área útil aqui.</li><li>Se sair muito papel em branco, confira o comprimento da bobina no driver. Guilhotina e avanço são configurados no driver, quando o modelo oferece essas opções. O site não envia comandos de corte ou de abertura de gaveta.</li>'+
      '<li><b>Jeito recomendado:</b> use o botão <b>Baixar configurador</b> no quadro “Impressão automática no Windows”. Ele acha a impressora de notinha pelo nome e cria o atalho que imprime só nela. Se preferir fazer à mão, siga os passos abaixo.</li>'+
      '<li>Deixe a impressora de notinha como <b>padrão</b>: em <b>Configurações do Windows → Impressoras e scanners</b>, desligue “Permitir que o Windows gerencie minha impressora padrão”, clique na impressora de notinha (por exemplo, a que começa com <b>MP-</b>, como MP-4200 TH) e escolha <b>Definir como padrão</b>. Na primeira impressão pelo Chrome, escolha essa mesma impressora no destino; o Chrome lembra dela nas próximas.</li>'+
      '<li>Para imprimir <b>sem perguntar nada</b>: clique com o botão direito na Área de Trabalho → <b>Novo → Atalho</b>, cole o comando abaixo, avance e dê o nome <b>Painel de pedidos</b>. Feche todas as janelas do Chrome e abra o painel sempre por esse atalho.<div class="copy-line"><code id="kiosk-cmd">'+esc(chromeCmd)+'</code><button type="button" class="btn secondary small" id="copy-kiosk">'+icon('copy')+' Copiar</button></div></li></ol>'+
      '<p class="muted">Para Bematech e Elgin, consulte os <a class="text-link" href="https://github.com/ElginDeveloperCommunity/Impressoras" target="_blank" rel="noopener">drivers oficiais</a>. Para outras marcas, use o site do fabricante.</p>'+
      '<h3>Impressão automática no caixa</h3><p class="muted">Mantenha o painel aberto e confirme o destino e o papel antes de ligar a impressão automática. O atalho acima usa o Chrome instalado no caminho padrão do Windows; se ele estiver em outro local, ajuste o caminho. A fila do site envia um documento por vez e aguarda a janela de impressão fechar. Fechar a janela não confirma que o papel saiu: confira a fila e o equipamento antes de reimprimir.</p>'+
      '<h3>Notinha de pedido e outros equipamentos</h3><p class="muted">Esta impressão é um comprovante de pedido, sem emissão de NFC-e/NF-e. Impressoras fiscais ECF, etiquetadoras, conexões apenas por comandos e impressoras embutidas em maquininhas precisam de integração específica. Android e iPhone dependem do serviço de impressão disponível no aparelho e do suporte do modelo.</p></details></section>';
  return '<section class="workspace-hero"><div class="workspace-hero-copy"><span class="workspace-kicker">DO PEDIDO AO PAPEL</span><h2>Uma notinha clara.<br>Uma operação mais leve.</h2><p>Ajuste o papel, confira a leitura e deixe cada pedido pronto para a cozinha ou para a entrega.</p><div class="workspace-hero-actions"><button type="button" class="btn" id="print-test">'+icon('print')+' Imprimir teste</button><button type="button" class="btn secondary" id="print-preview">'+icon('eye')+' Ver prévia</button></div><div class="workspace-summary"><span>'+icon('print')+' <span id="print-paper-summary">'+esc(printProfiles[paperWidth()].label)+'</span></span><span>'+icon('clock')+' <span id="print-auto-summary">'+(autoPrint()?'Impressão automática ligada':'Impressão manual')+'</span></span></div></div><div class="print-hero-symbol" aria-hidden="true">'+icon('print')+'<span>Feito para o seu caixa</span></div></section>'+
    '<div class="print-workspace">'+settings+'<aside class="print-preview-panel"><span class="eyebrow">PRÉVIA AO VIVO</span><h3>Como sua notinha vai sair</h3><p class="muted">Um pedido de exemplo, com os ajustes deste aparelho.</p><div class="print-preview-stage" tabindex="0" aria-label="Prévia da notinha com rolagem"><div id="print-live-sheet"></div></div><p class="print-preview-caption">'+icon('eye')+' A prévia acompanha o papel e o tamanho das letras.</p><div class="print-guidance"><b>Escolha sua impressora na janela de impressão</b><p>Bematech, Elgin e outras marcas dependem do driver instalado no Windows. Escolha o destino no Chrome ou Edge e confira a escala de 100%.</p></div></aside></div>'+
    agent+installer+'<section class="panel" id="print-history"></section><div class="print-guidance"><b>Confira antes de atender</b><p>O teste não cria pedidos nem movimenta o caixa. Confira acentos, valores e a linha de 20 mm. A prévia não confirma conexão com a impressora ou saída do papel.</p></div>'+help;
}
function updatePrintPreview(){
  const sheet=$('#print-live-sheet');if(!sheet)return;
  sheet.innerHTML=printJobHTML(sampleOrder())+calibrationHTML();styleTicketArea(sheet);
  $('#print-paper-summary').textContent=printProfiles[paperWidth()].label;
  $('#print-auto-summary').textContent=autoPrint()?'Impressão automática ligada':'Impressão manual';
}
async function bindAlertsPanel(){
  const status=$('#push-status'),toggle=$('#push-toggle'),test=$('#push-test');if(!status)return;
  const labels={on:'Ativado neste aparelho.',off:'Desativado neste aparelho.',denied:'Bloqueado: libere as notificações deste site nas configurações do navegador.',unsupported:'Este navegador não aceita avisos. No iPhone, use “Adicionar à Tela de Início” e abra o painel por lá.'};
  const draw=async()=>{const s=await pushState().catch(()=>'off');status.textContent=labels[s];toggle.textContent=s==='on'?'Desativar avisos':'Ativar avisos';toggle.disabled=s==='unsupported'||s==='denied';test.hidden=s!=='on';toggle.dataset.state=s;};
  toggle.onclick=async()=>{toggle.disabled=true;try{if(toggle.dataset.state==='on'){await disablePush();toast('Avisos desativados neste aparelho.');}else{await enablePush();toast('Avisos ativados! Teste para conferir.');}}catch(e){toast(e.message);}await draw();};
  test.onclick=async()=>{try{const r=await api('/api/admin/push/test',{method:'POST'});toast(r.sent?'Aviso de teste enviado.':'Nenhum aparelho ativo encontrado.');}catch(e){toast(e.message);}};
  $$('[data-goto]').forEach(b=>b.onclick=()=>switchTab(b.dataset.goto));
  draw();
}
function bindPrintPanel(){
  updatePrintPreview();
  mountPrintJournal($('#print-history'),async job=>{
    const {order}=await api('/api/admin/print-orders/'+job.order_id);
    if(order.status==='cancelled')throw Error('Este pedido foi cancelado. Confira com a equipe e dispense a pendência.');
    return printTicket(order,job.what);
  });
  $('#print-sector').onchange=e=>{try{localStorage.setItem('sca.print-sector.'+store.id,e.target.value.trim());toast('Setor de impressão atualizado neste aparelho.');}catch{toast('Não consegui salvar a preferência neste navegador.');}};
  $('#autoprint').onchange=e=>{setPref('autoprint',e.target.checked?'1':'0');e.target.nextElementSibling.textContent=e.target.checked?'Ligado':'Desligado';if(e.target.checked){printSeen=null;watchOrders();toast('Pedidos novos serão impressos com o painel aberto. Confira as pendências anteriores no histórico.');}};
  $('#print-role').onchange=e=>{setPref('print-role',e.target.value);toast({all:'Este computador imprime tudo.',counter:'Este computador imprime só a notinha do balcão.',kitchen:'Este computador imprime só a via da cozinha.'}[e.target.value]);};
  $('#kitchenslip').onchange=e=>{setPref('kitchenslip',e.target.checked?'1':'0');e.target.nextElementSibling.textContent=e.target.checked?'Ligado':'Desligado';};
  $('#driverslip').onchange=e=>{setPref('driverslip',e.target.checked?'1':'0');e.target.nextElementSibling.textContent=e.target.checked?'Ligado':'Desligado';};
  $('#paper-width').onchange=e=>{setPref('paper',e.target.value);const input=$('#print-content-width');input.max=printProfiles[paperWidth()].max;input.value=printContentWidth();$('#print-font').value=printFont();toast(printProfiles[paperWidth()].label+' neste aparelho.');};
  $('#print-content-width').onchange=e=>{const value=Number(e.target.value),max=printProfiles[paperWidth()].max;if(!Number.isFinite(value)||value<32||value>max){e.target.value=printContentWidth();toast('Informe uma área útil entre 32 e '+max+' mm.');return;}setPref('print-width.'+paperWidth(),String(value));toast('Área útil salva neste navegador.');};
  $('#print-font').onchange=e=>{setPref('print-font',e.target.value);toast('Tamanho das letras salvo.');};
  $('#print-preview').onclick=previewTicket;
  $('#print-test').onclick=()=>printTicket(sampleOrder(),'all',true);
  $('#copy-kiosk').onclick=()=>copy($('#kiosk-cmd').textContent);
  bindPrintAgent();
  $('#printer-pattern').onchange=e=>setPref('printer-pattern',e.target.value.trim()||'MP-');
  $('#printer-pattern-kitchen').onchange=e=>setPref('printer-pattern-kitchen',e.target.value.trim());
  $$('[name=printer-count]').forEach(r=>r.onchange=()=>{const two=r.value==='2'&&r.checked;setPref('printer-count',two?'2':'1');$('#kitchen-pattern-field').hidden=!two;$('#printer-pattern-label').textContent=two?'Impressora do balcão começa com':'A impressora de notinha começa com';});
  $('#download-installer').onclick=()=>{const pattern=$('#printer-pattern').value.trim()||'MP-',kitchen=$('#printer-pattern-kitchen').value.trim(),two=$('[name=printer-count][value="2"]').checked;
    if(two&&!kitchen){toast('Informe o começo do nome da impressora da cozinha.');$('#printer-pattern-kitchen').focus();return;}
    setPref('printer-pattern',pattern);setPref('printer-pattern-kitchen',kitchen);setPref('printer-count',two?'2':'1');
    const blob=new Blob([printerInstaller(pattern,$('#printer-startup').checked,two?kitchen:'')],{type:'application/octet-stream'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='Configurar-impressora-notinha.bat';document.body.append(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);
    toast('Configurador baixado. Abra o arquivo no computador da impressora.');};
  $$('#print-panel input,#print-panel select').forEach(input=>input.addEventListener('change',updatePrintPreview));
}
async function platformNotices(){
  try{const r=await api('/api/admin/notices');
    billing=r.billing;
    const closed=!store.open&&['owner','manager','cashier'].includes(role)&&(!r.billing||['exempt','active','paid','trial'].includes(r.billing.state))?'<div class="platform-notice alert billing-banner"><div><b>Sua loja está fechada: os clientes veem o cardápio, mas não conseguem pedir.</b><p>Abra a loja para receber pedidos'+(store.auto_hours?' (com o horário automático, ela abre e fecha sozinha nos horários configurados).':'.')+'</p></div><button class="btn small" id="open-store-now">Abrir loja agora</button></div>':'';
    $('#platform-notices').innerHTML=closed+billingBanner(r.billing)+(r.blocked_reason?'<div class="platform-notice alert"><b>Sua loja está bloqueada pela plataforma.</b><p>'+esc(r.blocked_reason)+' Fale com o suporte do SeuComércioAqui para regularizar.</p></div>':'')+
      r.notices.map(n=>'<div class="platform-notice '+esc(n.kind)+'"><b>'+esc(n.title)+'</b><p>'+esc(n.body)+'</p></div>').join('');
    $$('[data-subscribe]').forEach(b=>b.onclick=subscribeDialog);
    if($('#open-store-now'))$('#open-store-now').onclick=async()=>{try{store=(await api('/api/admin/store/open',{method:'POST',body:JSON.stringify({open:true})})).store;updateStoreButton();toast('Loja aberta para pedidos.');platformNotices();}catch(e){toast(e.message);}};
    if($('#billing-refresh'))$('#billing-refresh').onclick=refreshBilling;
  }catch{}
}
let billing=null;
const firstCharge=b=>b.first_charge?new Date(b.first_charge).toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}):'';
const planText=b=>money(b.price)+' por mês, cobrado no cartão pelo Mercado Pago'+(b.first_charge?' (a 1ª cobrança só em '+firstCharge(b)+', quando acaba seu mês grátis)':'');
function billingBanner(b){
  if(b&&b.state==='paid'&&b.days_left>0&&b.days_left<=2){
    const block=new Date(b.paid_until+'T12:00:00');block.setDate(block.getDate()+1);const day=block.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});
    const pay=role==='owner'?'<button class="btn small" data-subscribe>Pagar a mensalidade</button>':'<p class="muted">Avise o dono da loja.</p>';
    return '<div class="platform-notice alert billing-banner"><div><b>'+(b.days_left===1?'Último dia: amanhã ('+day+') a loja é bloqueada.':'Sua mensalidade vence em 2 dias: a loja bloqueia dia '+day+'.')+'</b><p>Pague '+money(b.price)+' para continuar recebendo pedidos sem parar.</p></div>'+pay+'</div>';
  }
  if(!b||['exempt','active','paid'].includes(b.state))return '';
  const owner=role==='owner';
  const button=label=>owner?'<button class="btn small" data-subscribe>'+label+'</button>':'<p class="muted">Peça ao dono da loja para assinar.</p>';
  if(b.state==='trial')return '<div class="platform-notice promo billing-banner"><div><b>Mês grátis até '+new Date(b.trial_until).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+'</b><p>Assine já para não parar de vender: '+planText(b)+'.</p></div>'+button('Assinar agora')+'</div>';
  if(b.state==='pending')return '<div class="platform-notice alert billing-banner"><div><b>Falta concluir a assinatura no Mercado Pago.</b><p>'+(owner?'Se você já cadastrou o cartão, clique em “Já assinei”.':'')+'</p></div>'+(owner?'<div class="row-actions"><button class="btn small" data-subscribe>Continuar assinatura</button><button class="btn secondary small" id="billing-refresh">Já assinei</button></div>':'')+'</div>';
  const why={paused:'A cobrança automática está pausada.',cancelled:'A assinatura foi cancelada.',expired:'O período liberado terminou.'}[b.state]||'A assinatura não está ativa.';
  return '<div class="platform-notice alert billing-banner"><div><b>Sua loja está pausada e não recebe pedidos.</b><p>'+why+' Assine para voltar a vender: '+planText(b)+'.</p></div>'+button('Assinar e voltar a vender')+'</div>';
}
async function refreshBilling(){try{billing=await api('/api/admin/billing/sync',{method:'POST'});toast(['active','paid'].includes(billing.state)?'Assinatura ativa. Boas vendas!':'Ainda não recebemos a confirmação do Mercado Pago. Tente em alguns minutos.');store=(await api('/api/admin/store')).store;updateStoreButton();platformNotices();if(tab==='settings')settingsPage();}catch(e){toast(e.message);}}
function subscribeDialog(){
  const b=billing||{price:5999,free_months:0};
  const dialog=modal('Assinar o SeuComércioAqui','<div class="pay-choice" role="tablist"><button type="button" class="chip active" data-pay="card">'+icon('wallet')+' Cartão (automático)</button><button type="button" class="chip" data-pay="pix">'+icon('copy')+' Pix (paga o mês)</button></div><div id="pix-pay" hidden><p class="muted">Pague '+money(b.price)+' por Pix para liberar um mês. O Pix não é recorrente: o próximo mês precisa de outro pagamento. Se já houver cobrança automática no cartão, atualize essa assinatura antes de mudar.</p><button type="button" class="btn full" id="make-pix">Gerar Pix de '+money(b.price)+'</button><div id="pix-area"></div></div><form id="subscribe-form"><div class="plan-card"><b>Plano completo</b><strong>'+money(b.price)+'<small>/mês</small></strong>'+(b.first_charge?'<span class="badge green">1ª cobrança só em '+firstCharge(b)+', no fim do mês grátis</span>':'')+'<p class="muted">Cardápio, pedidos, equipe, relatórios, pagamento online e avisos. Cancele as próximas cobranças quando quiser.</p></div>'+field('payer_email','E-mail da sua conta do Mercado Pago',b.payer_email||auth.user.email,'email','required maxlength="254"')+'<p class="muted">Você será direcionado ao checkout seguro do Mercado Pago para autorizar o cartão. '+(b.free_months?'O período gratuito vale uma vez por loja; ':'')+'A cobrança de '+money(b.price)+' é mensal e automática. A autorização do cartão e a confirmação do pagamento são etapas distintas.</p><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Ir para o Mercado Pago '+icon('arrow')+'</button></form>');
  const epoch=Symbol('billing');dialog._billingEpoch=epoch;const form=$('#subscribe-form',dialog);
  const active=()=>dialog.open&&dialog._billingEpoch===epoch&&dialog.contains(form);
  bindForm(form,async values=>{const r=await api('/api/admin/billing/subscribe',{method:'POST',body:JSON.stringify({payer_email:values.get('payer_email')})});if(active())location.href=r.init_point;});
  $$('[data-pay]',dialog).forEach(btn=>btn.onclick=()=>{$$('[data-pay]',dialog).forEach(x=>x.classList.toggle('active',x===btn));$('#pix-pay',dialog).hidden=btn.dataset.pay!=='pix';form.hidden=btn.dataset.pay==='pix';});
  let poll,clock,checking=false;
  const stop=()=>{clearInterval(poll);clearInterval(clock);};dialog.addEventListener('close',stop,{once:true});
  const paid=()=>{stop();if(active()){closeModal();toast('Pagamento confirmado! O período da loja foi atualizado.');refreshBilling();}};
  $('#make-pix',dialog).onclick=async e=>{
    const button=e.currentTarget;button.disabled=true;
    try{
      const r=await api('/api/admin/billing/pix',{method:'POST'});if(!active())return;
      if(r.paid){paid();return;}
      $('#pix-area',dialog).innerHTML='<img class="pix-qr" src="/api/admin/billing/pix.svg?t='+Date.now()+'" alt="QR Code Pix" width="220" height="220"><div class="pix-key"><code>'+esc(r.code)+'</code><button type="button" class="btn secondary small" id="copy-plan-pix">'+icon('copy')+' Copia e cola</button></div><p class="notice" id="pix-wait" role="status">Aguardando pagamento. Confirmação pelo Mercado Pago.</p><p class="muted" id="pix-expiration"></p><button type="button" class="btn secondary small" id="check-plan-pix">Já paguei, conferir</button>';
      button.hidden=true;$('#copy-plan-pix',dialog).onclick=()=>copy(r.code);
      const check=async manual=>{
        if(!active()||checking)return;checking=true;
        try{
          const c=await api('/api/admin/billing/pix/check',{method:'POST'});if(!active())return;
          if(c.paid){paid();return;}
          if(c.expired){stop();$('#pix-wait',dialog).textContent='Este código expirou. Se você pagou, confira antes de gerar outro.';button.hidden=false;button.textContent='Conferir e gerar novo Pix';}
          else if(manual)$('#pix-wait',dialog).textContent='Pagamento ainda não confirmado. A consulta continua automaticamente.';
        }catch(error){if(manual&&active())$('#pix-wait',dialog).textContent=error.message;}
        finally{checking=false;}
      };
      const expires=Date.parse(r.expires);
      const countdown=()=>{if(!active()){stop();return;}const seconds=Math.max(0,Math.ceil((expires-Date.now())/1000));$('#pix-expiration',dialog).textContent=seconds?'Válido por '+Math.floor(seconds/60)+' min e '+seconds%60+' s.':'Validade encerrada. Clique em conferir para verificar o pagamento.';};
      $('#check-plan-pix',dialog).onclick=()=>check(true);stop();countdown();clock=setInterval(countdown,1000);poll=setInterval(()=>check(false),6000);
    }catch(error){if(active())toast(error.message);}finally{if(active())button.disabled=false;}
  };
}
function planPanel(){
  if(role!=='owner'||!billing)return '';
  const b=billing,labels={exempt:['green','Uso gratuito'],active:['green','Assinatura ativa'],paid:['green','Pago'],trial:['amber','Em teste grátis'],pending:['amber','Aguardando o cartão'],paused:['red','Cobrança pausada'],cancelled:['gray','Cancelada'],expired:['red','Sem assinatura']};
  const [color,label]=labels[b.state]||['gray',b.state];
  return '<section class="panel"><div class="section-heading"><div><h2>Seu plano</h2><p class="muted">'+(b.state==='exempt'?'Esta loja tem uso gratuito permanente.':planText(b)+'.')+'</p></div><span class="badge '+color+'">'+label+'</span></div>'+
    (b.next_payment?'<div class="payment-line"><span>Próxima cobrança</span><b>'+new Date(b.next_payment).toLocaleDateString('pt-BR')+'</b></div>':'')+(b.paid_until?'<div class="payment-line"><span>Liberada até</span><b>'+new Date(b.paid_until+'T12:00:00').toLocaleDateString('pt-BR')+'</b></div>':'')+
    ((b.payments||[]).length?'<details><summary>Histórico de pagamentos do plano</summary>'+b.payments.map(p=>'<div class="payment-line"><span>'+esc(p.description)+'<small class="muted">'+(p.paid_at?' • aprovado em '+new Date(p.paid_at).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):' • registrado em '+new Date(p.created_at).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}))+'</small></span><b>'+money(p.amount)+'</b></div>').join('')+'</details>':'')+
    (b.state==='exempt'?'':'<div class="row-actions">'+(['authorized','pending','paused'].includes(b.sub_status)?'<a class="btn secondary small" href="'+b.manage_url+'" target="_blank" rel="noopener">Trocar cartão no Mercado Pago</a><button type="button" class="btn secondary small danger-text" id="cancel-plan">Cancelar assinatura</button>':'<button type="button" class="btn small" data-subscribe>Assinar</button>')+'<button type="button" class="btn secondary small" id="billing-refresh-2">Atualizar situação</button></div>')+'</section>';
}
function bindPlanPanel(){
  $$('[data-subscribe]').forEach(b=>b.onclick=subscribeDialog);
  if($('#billing-refresh-2'))$('#billing-refresh-2').onclick=refreshBilling;
  if($('#cancel-plan'))$('#cancel-plan').onclick=()=>{modal('Cancelar a assinatura?','<p>Não haverá novas cobranças. A loja continua funcionando até o fim do período já pago e depois para de receber pedidos.</p><button id="confirm-cancel-plan" class="btn danger full">Cancelar assinatura</button>');$('#confirm-cancel-plan').onclick=async()=>{try{billing=await api('/api/admin/billing/cancel',{method:'POST'});closeModal();toast('Assinatura cancelada.');settingsPage();platformNotices();}catch(e){toast(e.message);}};};
}
async function switchTab(next,quiet=false){
  clearTimeout(timer);$('#dashboard-content')._inboxCleanup?.();$('#new-manual-order')?.remove();tab=next;$('#dashboard-content').dataset.management=next;const v=++generation;$('#dashboard-content').classList.toggle('marketing-surface',next==='marketing');
  const titles={receivables:['Recebíveis online','Pagamentos, taxas e previsão de liberação na conta Mercado Pago.'],diagnostics:['Diagnóstico da loja','Filas, pagamentos e pontos para conferir na operação.'],fiscal:['Fiscal da sua loja','Seu espaço para notas e documentos, com cada etapa no lugar.'],network:['Minha rede','Um link público para reunir as unidades.'],deliverymap:['Mapa de entregas','Pedidos prontos, saídas em lote e posições recentes.'],inbox:['Atendimento WhatsApp','Conversas, respostas e responsáveis pelo atendimento.'],pos:['PDV / Balcão','Venda rápida com catálogo, escolhas e sacola.'],cash:['Caixa por turno','Conferência, recebimentos parciais e estornos.'],dining:['Mesas e comandas','Contas abertas, pedidos e atendimento do salão.'],promotions:['Promoções e horários','Preços e disponibilidade programados por canal.'],purchasing:['Contas e fornecedores','Vencimentos, baixas e produção de preparos.'],reports:['Gerar relatório','Escolha o período e baixe os números da loja.'],marketing:['Mais motivos para voltar','Relacionamento, recompra e oportunidades de venda.'],ingredients:['Da receita ao resultado','Ingredientes, consumo e custo de cada produto.'],kitchen:['Fila de produção','Produtos e observações para preparar os pedidos.'],finance:['Seu lucro, com clareza','Custos, taxas e resultado estimado da loja.'],stock:['Estoque sob controle','Reposição, perdas e histórico de movimentações.'],customers:['Conheça seus clientes','Compras e histórico de quem pede na sua loja.'],integrations:['Conecte seus parceiros','Chaves de API e acompanhamento das entregas.'],printing:['Imprimir notinha','Impressora térmica, largura do papel, via do motoboy e teste de impressão.'],support:['Fale com o suporte','Dúvidas, problemas e sugestões direto com a equipe SeuComércioAqui.'],overview:['Seu dia em um olhar','Os pedidos e números que importam agora.'],orders:['Cada pedido, no seu tempo','Do primeiro clique à última entrega.'],products:['Seu cardápio, sua assinatura','Organize seus produtos e deixe tudo com a sua cara.'],drivers:['Entrega bem cuidada','Sua equipe e os pedidos a caminho.'],sales:['Os números do seu negócio','Acompanhe vendas, recebimentos e despesas.'],settings:['A sua loja, do seu jeito','Identidade, contato e operação em um só lugar.']};
  $('#page-title').textContent=titles[tab][0];$('#page-subtitle').textContent=titles[tab][1];$$('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  if(!quiet)$('#dashboard-content').innerHTML='<div class="loading small-loading">Carregando…</div>';
  try{
    if(tab==='overview'||tab==='orders'||tab==='kitchen'){
      const [result,team,today,week]=await Promise.all([api('/api/admin/orders'),api('/api/admin/drivers'),tab==='overview'?api('/api/admin/summary?days=1'):null,tab==='overview'?api('/api/admin/summary?days=7'):null]);
      if(v!==generation)return;orders=result.orders;drivers=team.drivers;
      if(tab==='overview')overview(today,week);else if(tab==='kitchen')kitchenPage();else ordersPage();
      timer=setTimeout(()=>{if(!document.hidden)switchTab(tab,true);else timer=setTimeout(()=>switchTab(tab,true),12000);},12000);
    }else if(tab==='products'){
      const result=await api('/api/admin/products');if(v!==generation)return;products=result.products;categories=result.categories;productsPage();
    }else if(tab==='drivers'){
      const [result,team]=await Promise.all([api('/api/admin/orders'),api('/api/admin/drivers')]);if(v!==generation)return;orders=result.orders;drivers=team.drivers;driversPage();
    }else if(tab==='sales'){
      const summary=await api('/api/admin/summary?days='+period);if(v!==generation)return;salesPage(summary);
    }else if(tab==='receivables'){await receivablesPage($('#dashboard-content'));}
    else if(tab==='diagnostics'){await operationsHealthPage($('#dashboard-content'),switchTab);}
    else if(['finance','stock','customers','integrations'].includes(tab)){await managementView(tab,$('#dashboard-content'));}
    else if(tab==='network'){await networkSettings($('#dashboard-content'));}
    else if(tab==='deliverymap'){await deliveryMapPage($('#dashboard-content'));}
    else if(tab==='inbox'){await inboxPage($('#dashboard-content'));}
    else if(tab==='marketing'){await growthPage($('#dashboard-content'));}
    else if(['pos','cash','dining','promotions','purchasing','reports'].includes(tab)){await operationsPage(tab,$('#dashboard-content'));}
    else if(tab==='ingredients'){await inventoryPage($('#dashboard-content'));}
    else if(tab==='fiscal'){fiscalPage($('#dashboard-content'),switchTab);}
    else if(tab==='printing'){$('#dashboard-content').innerHTML=printPanel();bindPrintPanel();}
    else if(tab==='support'){await supportPage($('#dashboard-content'));if(v===generation)supportBadge(0);}else settingsPage();
    attachFallbacks($('#dashboard-content'));
  }catch(e){if(v!==generation)return;if(e.status===401){location.href='/entrar';return;}$('#dashboard-content').innerHTML=empty('Não foi possível carregar',e.message,'<button id="retry-tab" class="btn secondary">Tentar novamente</button>');$('#retry-tab').onclick=()=>switchTab(tab);}
}
function metric(label,value,type='chart',note=''){
  return '<article class="metric"><span class="metric-icon">'+icon(type)+'</span><div><small>'+label+'</small><strong>'+value+'</strong>'+(note?'<span class="metric-note">'+note+'</span>':'')+'</div></article>';
}
function chart(data){
  const maximum=Math.max(1,...data.map(x=>x.total));
  return '<div class="chart" aria-label="Vendas concluídas por dia">'+data.map(x=>'<div class="chart-column"><div class="chart-value">'+money(x.total)+'</div><div class="chart-bar" style="height:'+Math.max(2,x.total/maximum*100)+'%"></div><small>'+new Date(x.date+'T12:00:00').toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'})+'</small></div>').join('')+'</div>';
}
function overview(today,week){
  const active=orders.filter(o=>!['completed','cancelled'].includes(o.status));
  $('#dashboard-content').innerHTML=(['owner','manager'].includes(role)?'<section id="merchant-setup"></section>':'')+'<div class="metrics three">'+metric('Vendas concluídas hoje',money(today.revenue),'chart')+metric('Pedidos hoje',today.orders,'bag')+metric('Em andamento',active.length,'clock')+'</div><section class="panel order-panel"><div class="section-heading"><div><h2>Pedidos em andamento</h2><p class="muted">Um próximo passo para cada pedido.</p></div><button id="all-orders" class="text-link">Ver todos '+icon('arrow')+'</button></div>'+orderBoard(active)+'</section><div class="overview-bottom"><section class="panel"><div class="section-heading"><div><span class="muted">Vendas concluídas • últimos 7 dias</span><h2>'+money(week.revenue)+'</h2></div>'+icon('chart')+'</div>'+chart(week.chart)+'</section><section class="share-panel"><span class="feature-icon">'+icon('link')+'</span><h2>Seu cardápio está no ar.</h2><p>Compartilhe o link e receba pedidos diretamente pela sua loja.</p><button id="share-store" class="btn">'+icon('copy')+' Copiar link da loja</button></section></div>'+(!products.length&&!store.open?'<p class="muted">Primeiros passos: cadastre seus produtos, configure pagamentos e abra a loja quando estiver tudo pronto.</p>':'');
  $('#dashboard-content').insertAdjacentHTML('beforeend','<section id="overview-details"></section>');overviewDetails($('#overview-details')).catch(e=>toast(e.message));
  if(['owner','manager'].includes(role))setupPanel($('#merchant-setup'),switchTab).catch(e=>toast(e.message));
  $('#all-orders').onclick=()=>switchTab('orders');$('#share-store').onclick=()=>copy(location.origin+'/loja/'+store.slug);bindOrderButtons();
}
const laneState=()=>{try{return JSON.parse(localStorage.getItem('sca.lanes')||'{}');}catch{return {};}};
function saveLanes(state){try{localStorage.setItem('sca.lanes',JSON.stringify(state));}catch{}}
function orderBoard(list){
  const state=laneState();
  return '<div class="order-board'+(state.focus?' focused':'')+'">'+[['new','Novos'],['preparing','Em preparo'],['ready','Prontos'],['delivering','Em entrega']].map(([status,label])=>{
    const filtered=list.filter(o=>o.status===status), collapsed=state[status]==='closed'&&state.focus!==status, hidden=state.focus&&state.focus!==status;
    return '<section class="order-lane lane-'+status+(collapsed||hidden?' collapsed':'')+(state.focus===status?' expanded':'')+'" data-lane="'+status+'"><h3><button class="lane-tab" data-lane-toggle="'+status+'" aria-expanded="'+!(collapsed||hidden)+'" title="'+(collapsed||hidden?'Abrir coluna':'Recolher coluna')+'"><i></i><span class="lane-name">'+label+'</span><span class="lane-count">'+filtered.length+'</span></button><button class="lane-focus icon-btn" data-lane-focus="'+status+'" aria-label="'+(state.focus===status?'Voltar às 4 colunas':'Ampliar '+label)+'" title="'+(state.focus===status?'Voltar às 4 colunas':'Ampliar esta coluna')+'">'+icon(state.focus===status?'close':'eye')+'</button></h3><div class="lane-scroll">'+filtered.map(orderCard).join('')+(!filtered.length?'<p class="lane-empty">Tudo em dia por aqui.</p>':'')+'</div></section>';
  }).join('')+'</div>';
}
function bindLanes(){
  $$('[data-lane-toggle]').forEach(b=>b.onclick=()=>{const s=laneState(),k=b.dataset.laneToggle;if(s.focus&&s.focus!==k){s.focus=k;}else{s[k]=s[k]==='closed'?'open':'closed';if(s.focus===k)delete s.focus;}saveLanes(s);switchTab(tab,true);});
  $$('[data-lane-focus]').forEach(b=>b.onclick=()=>{const s=laneState(),k=b.dataset.laneFocus;if(s.focus===k)delete s.focus;else{s.focus=k;s[k]='open';}saveLanes(s);switchTab(tab,true);});
}
function nextStatus(order){if(onlineMethod(order)&&!order.paid)return null;return {new:'preparing',preparing:'ready',ready:order.mode==='delivery'?'delivering':'completed',delivering:'completed'}[order.status];}
function actionLabel(order){return {new:'Aceitar pedido',preparing:'Marcar pronto',ready:order.mode==='delivery'?'Saiu para entrega':'Concluir retirada',delivering:'Concluir entrega'}[order.status];}
function orderCard(o){
  const minutes=Math.max(0,Math.round((Date.now()-new Date(o.created_at).getTime())/60000));
  return '<article class="order-card"><button class="order-detail" data-detail="'+o.id+'" aria-label="Ver pedido '+o.number+'"><div class="order-top"><b>#'+o.number+'</b><small>'+ (minutes<60?'há '+minutes+' min':date(o.created_at))+'</small></div><div class="order-customer"><span class="avatar">'+esc(o.customer.split(' ').slice(0,2).map(x=>x[0]).join('').toUpperCase())+'</span><div><b>'+esc(o.customer)+'</b><small>'+esc(o.items.map(x=>x.quantity+' × '+x.name).join(', '))+'</small></div></div><div class="order-meta"><span class="badge tiny">'+icon(o.mode==='delivery'?'truck':'bag')+(o.mode==='delivery'?'Entrega':'Retirada')+'</span>'+(o.scheduled_for?'<span class="badge tiny amber" title="Pedido agendado">'+icon('clock')+new Date(o.scheduled_for).toLocaleString('pt-BR',{weekday:'short',hour:'2-digit',minute:'2-digit'})+'</span>':'')+(o.motoja&&o.motoja.status?'<span class="badge tiny '+(['erro','cancelado'].includes(o.motoja.status)?'red':o.motoja.status==='na_fila'?'amber':'green')+'" title="MotoJá">'+icon('truck')+esc(o.motoja.label)+'</span>':'')+(o.rating?'<span class="badge tiny" title="Avaliação do cliente">'+'★'.repeat(o.rating)+'</span>':'')+'<strong>'+money(o.total)+'</strong></div>'+(onlineMethod(o)&&!o.paid?'<span class="badge tiny amber">Aguardando pagamento online</span>':'')+'</button>'+ (nextStatus(o)?'<button class="btn small full order-next '+(o.status==='preparing'?'lime':'')+'" data-next="'+o.id+'">'+actionLabel(o)+'</button>':'')+'</article>';
}
function bindOrderButtons(){
  if(!$('#new-manual-order')&&['orders','overview'].includes(tab)){$('.title-actions').insertAdjacentHTML('afterbegin','<button id="new-manual-order" class="btn secondary">'+icon('plus')+' Novo pedido</button>');$('#new-manual-order').onclick=()=>manualOrder(()=>switchTab('orders'));}
  bindLanes();
  $$('[data-detail]').forEach(b=>b.onclick=()=>orderDialog(orders.find(o=>o.id===Number(b.dataset.detail))));
  $$('[data-next]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const order=orders.find(o=>o.id===Number(b.dataset.next));await api('/api/admin/orders/'+order.id,{method:'PATCH',body:JSON.stringify({status:nextStatus(order)})});toast('Pedido atualizado.');await switchTab(tab,true);}catch(e){toast(e.message);b.disabled=false;}});
}
function ordersPage(){
  $('#dashboard-content').innerHTML='<div class="page-toolbar"><div class="chips"><button class="chip active" data-filter="active">Em andamento</button><button class="chip" data-filter="completed">Concluídos</button><button class="chip" data-filter="cancelled">Cancelados</button></div><label class="search compact">'+icon('search')+'<span class="sr-only">Buscar pedido</span><input id="order-search" placeholder="Número, cliente, telefone ou endereço"></label></div><div id="orders-area">'+orderBoard(orders.filter(o=>!['completed','cancelled'].includes(o.status)))+'</div><p class="muted">Em andamento: todos os pedidos ativos. Histórico: até 500 pedidos por status.</p>';
  let filter='active';
  async function show(){
    const term=$('#order-search').value;
    const list=orders.filter(o=>(filter==='active'?!['completed','cancelled'].includes(o.status):o.status===filter)&&matchesSearch(term,[o.customer,o.number,o.phone,o.address,o.zone]));
    $('#orders-area').innerHTML=filter==='active'?orderBoard(list):list.length?'<div class="history-grid">'+list.map(orderCard).join('')+'</div>':empty('Nenhum pedido neste filtro','Os pedidos aparecem aqui conforme a operação avança.');
    bindOrderButtons();
  }
  $$('[data-filter]').forEach(b=>b.onclick=async()=>{
    filter=b.dataset.filter;$$('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));
    if(filter!=='active'){try{orders=(await api('/api/admin/orders?status='+filter)).orders;clearTimeout(timer);}catch(e){toast(e.message);}}
    else orders=(await api('/api/admin/orders')).orders;
    show();
  });$('#order-search').oninput=show;bindOrderButtons();
}
function orderDialog(o){
  const d=modal('Pedido #'+o.number,'<div class="order-dialog-top"><div><h3>'+esc(o.customer)+'</h3><p>'+esc(o.phone)+' • '+date(o.created_at)+'</p><span class="badge">'+statuses[o.status]+'</span></div><div class="drawer-tools"><a class="btn secondary small" target="_blank" rel="noopener" href="https://wa.me/'+o.phone.replace(/\D/g,'').replace(/^(?!55)/,'55')+'?text='+encodeURIComponent('Olá, '+o.customer.split(' ')[0]+'! Sobre o seu pedido #'+o.number+':')+'">WhatsApp</a><button id="print-order" class="btn secondary small">'+icon('print')+' Imprimir</button>'+(o.mode==='delivery'?'<button id="print-driver" class="btn secondary small">'+icon('truck')+' Via do motoboy</button>':'')+'</div></div>'+(nextStatus(o)?'<button id="drawer-next" class="btn full drawer-next">'+actionLabel(o)+' '+icon('arrow')+'</button>':'')+'<div class="notice">'+icon(o.mode==='delivery'?'truck':'store')+' '+(o.mode==='delivery'?'Entrega: '+esc(o.address)+(o.zone?' • Bairro '+esc(o.zone):''):'Retirada no balcão')+'</div>'+(o.mode==='delivery'&&(store.motoja_connected||o.motoja.status)?'<div class="motoja-box"><div><b>'+icon('truck')+' MotoJá</b><span>'+esc(o.motoja.label||'Motoboy ainda não chamado')+(o.motoja.motoboy?' • '+esc(o.motoja.motoboy):'')+'</span>'+(o.motoja.message&&['erro','na_fila','cancelado'].includes(o.motoja.status)?'<small>'+esc(o.motoja.message)+'</small>':'')+'</div><div class="row-actions">'+(o.motoja.trackingUrl?'<a class="btn secondary small" href="'+esc(o.motoja.trackingUrl)+'" target="_blank" rel="noopener">Ver motoboy</a>':'')+(store.motoja_connected&&!['chamado','aceito','retirado','entregue'].includes(o.motoja.status)&&!['completed','cancelled'].includes(o.status)?'<button class="btn small" id="call-motoja">Chamar MotoJá</button>':'')+'</div></div>':'')+o.items.map(x=>'<div class="tracking-item"><div><b>'+x.quantity+' × '+esc(x.name)+'</b><small>'+x.extras.map(e=>esc(e.name)).join(', ')+'</small><small>'+esc(x.notes)+'</small></div><b>'+money(x.unit_price*x.quantity)+'</b></div>').join('')+
  (o.notes?'<p class="notice">Observações: '+esc(o.notes)+'</p>':'')+'<div class="checkout-totals"><div><span>Produtos</span><b>'+money(o.subtotal)+'</b></div><div><span>Entrega</span><b>'+money(o.delivery_fee)+'</b></div><div><span>Desconto</span><b>− '+money(o.discount)+'</b></div><div class="total-row"><span>Total</span><strong>'+money(o.total)+'</strong></div></div><p>'+pay[o.payment]+(o.change_for?' • Troco para '+money(o.change_for):'')+'</p><form id="order-update">'+
  merchantPayment(o,role)+'<label class="check-row"><span><input name="paid" type="checkbox" '+(o.paid?'checked':'')+' '+(o.status==='cancelled'||onlineMethod(o)?'disabled':'')+'>Pagamento confirmado</span></label>'+
  (o.mode==='delivery'?'<label>Entregador<select name="driver_id"><option value="">Sem entregador</option>'+drivers.filter(x=>x.active||x.id===o.driver_id).map(x=>'<option value="'+x.id+'" '+(x.id===o.driver_id?'selected':'')+'>'+esc(x.name)+'</option>').join('')+'</select></label>':'')+
  '<p class="form-error" role="alert" hidden></p><div class="dialog-actions"><button class="btn" type="submit">Salvar atualização</button><button class="btn secondary" id="copy-track" type="button">'+icon('link')+' Link do pedido</button></div></form>'+
  (!['completed','cancelled'].includes(o.status)?'<button id="cancel-order" class="text-danger">Cancelar pedido</button>':'')+'<details class="help"><summary>Histórico do pedido</summary>'+o.events.map(e=>'<p>'+statuses[e.status]+' • '+date(e.created_at)+'</p>').join('')+'</details>','drawer');
  bindMerchantPayment(o,()=>switchTab(tab,true));
  if($('#call-motoja'))$('#call-motoja').onclick=async e=>{e.target.disabled=true;e.target.textContent='Chamando…';try{const r=await api('/api/admin/orders/'+o.id+'/motoja',{method:'POST'});toast(r.label+(r.message&&r.status!=='chamado'?': '+r.message:''));closeModal();switchTab(tab,true);}catch(err){toast(err.message);e.target.disabled=false;e.target.textContent='Chamar MotoJá';}};
  if($('#drawer-next'))$('#drawer-next').onclick=async e=>{e.target.disabled=true;try{await api('/api/admin/orders/'+o.id,{method:'PATCH',body:JSON.stringify({status:nextStatus(o)})});closeModal();toast('Pedido atualizado.');switchTab(tab,true);}catch(err){toast(err.message);e.target.disabled=false;}};
  $('.dialog-actions',d).insertAdjacentHTML('beforeend','<button id="order-costs" type="button" class="btn secondary">Conferir custos</button>');$('#order-costs').onclick=()=>costsDialog(o,()=>switchTab(tab,true));
  $('#print-order').onclick=()=>printTicket(o);if($('#print-driver'))$('#print-driver').onclick=()=>printTicket(o,'driver');$('#copy-track').onclick=()=>copy(location.origin+'/pedido/'+o.tracking_token);
  bindForm($('#order-update'),async form=>{await api('/api/admin/orders/'+o.id,{method:'PATCH',body:JSON.stringify({paid:o.status==='cancelled'||onlineMethod(o)?!!o.paid:form.has('paid'),driver_id:form.get('driver_id')?Number(form.get('driver_id')):null})});closeModal();toast('Pedido atualizado.');switchTab(tab,true);});
  if($('#cancel-order'))$('#cancel-order').onclick=()=>{
    const confirm=modal('Cancelar este pedido?','<p>O pedido #'+o.number+' será cancelado. Os itens voltarão ao estoque. O pagamento online não é estornado ao cancelar. Depois, confira o pagamento e use Estornar pagamento quando necessário.</p><div class="dialog-actions"><button id="confirm-cancel" class="btn danger">Confirmar cancelamento</button><button id="keep-order" class="btn secondary">Manter pedido</button></div>');
    $('#keep-order').onclick=()=>orderDialog(o);
    $('#confirm-cancel').onclick=async()=>{try{await api('/api/admin/orders/'+o.id,{method:'PATCH',body:JSON.stringify({status:'cancelled'})});closeModal();toast('Pedido cancelado.');switchTab(tab,true);}catch(e){toast(e.message);}};
  };
}
function productsPage(){
  $('#dashboard-content').innerHTML='<div class="page-toolbar"><div class="chips"><button class="chip active" id="catalog-tab">Produtos</button><button class="chip" id="coupon-tab">Cupons</button></div><div class="toolbar-actions"><button id="import-btn" class="btn secondary">'+icon('copy')+' Importar planilha</button><button id="categories-btn" class="btn secondary">'+icon('tag')+' Categorias</button><button id="new-product" class="btn">'+icon('plus')+' Novo produto</button></div></div><div class="metrics three">'+metric('Produtos cadastrados',products.length,'store')+metric('Disponíveis',products.filter(p=>p.active&&p.stock!==0).length,'check')+metric('Estoque baixo',products.filter(p=>p.active&&p.stock!==null&&p.stock<5).length,'bag')+'</div><section class="panel"><div class="section-heading"><h2>Produtos da loja</h2><label class="search compact">'+icon('search')+'<span class="sr-only">Buscar produto</span><input id="product-search" placeholder="Buscar produto"></label></div><div id="admin-products"></div></section>';
  $('#new-product').onclick=()=>productEditor();$('#categories-btn').onclick=categoriesDialog;$('#import-btn').onclick=importDialog;$('#coupon-tab').onclick=couponsPage;$('#catalog-tab').onclick=productsPage;
  $('#product-search').oninput=renderProductTable;renderProductTable();
}
function renderProductTable(){
  const search=$('#product-search').value;
  const list=products.filter(p=>productMatches(p,search,categories));
  $('#admin-products').innerHTML=list.length?'<div class="table-wrap"><table><thead><tr><th>Produto</th><th>Categoria</th><th>Preço</th><th>Estoque</th><th>Status</th><th><span class="sr-only">Ações</span></th></tr></thead><tbody>'+list.map(p=>'<tr><td><div class="table-product"><img src="'+esc(image(p.image))+'" alt=""><div><b>'+esc(p.name)+'</b><small>'+esc(p.description)+'</small></div></div></td><td>'+esc(categories.find(c=>c.id===p.category_id)?.name||'Outros')+'</td><td>'+money(p.price)+'</td><td>'+(p.stock===null?'Sem controle':p.stock+' un.')+'</td><td><span class="badge '+(p.active&&p.stock!==0?'green':'gray')+'">'+(p.active?(p.stock===0?'Esgotado':'Ativo'):'Pausado')+'</span></td><td><button class="icon-btn" data-edit-product="'+p.id+'" aria-label="Editar '+esc(p.name)+'">'+icon('edit')+'</button></td></tr>').join('')+'</tbody></table></div>':empty('Seu cardápio começa aqui','Adicione uma foto, um nome e um preço ao primeiro produto.','<button class="btn" id="empty-product">Adicionar produto</button>');
  $$('[data-edit-product]').forEach(b=>b.onclick=()=>productEditor(products.find(p=>p.id===Number(b.dataset.editProduct))));
  if($('#empty-product'))$('#empty-product').onclick=()=>productEditor();attachFallbacks($('#admin-products'));
}
function uploadField(name,label,value='',bank=false){
 return '<label>'+label+'<div class="upload-row">'+(bank?'<img class="upload-preview" data-preview="'+name+'" src="'+esc(image(value))+'" alt=""'+(value?'':' hidden')+'>':'')+'<input name="'+name+'" value="'+esc(value)+'" placeholder="URL HTTPS ou envie uma foto"><input type="file" accept="image/jpeg,image/png,image/webp" data-upload="'+name+'" aria-label="Enviar '+label+'">'+(bank?'<button type="button" class="btn secondary small" data-bank="'+name+'">'+icon('search')+' Escolher no banco de imagens</button>':'')+'</div><small>Fotos de até 8 MB. A imagem é otimizada no servidor.'+(bank?' Sem foto? Use uma imagem ilustrativa do banco.':'')+'</small></label>';
}
function bindUploads(root){
  const preview=name=>{const img=$('[data-preview="'+name+'"]',root);if(!img)return;const value=$('[name='+name+']',root).value.trim();img.hidden=!value;if(value)img.src=value;};
  $$('[data-preview]',root).forEach(img=>{img.addEventListener('error',()=>img.hidden=true);$('[name='+img.dataset.preview+']',root).addEventListener('change',()=>preview(img.dataset.preview));});
  $$('[data-bank]',root).forEach(button=>button.onclick=async()=>{
    try{await openImageBank($('[name=name]',root)?.value||'',url=>{$('[name='+button.dataset.bank+']',root).value=url;preview(button.dataset.bank);toast('Imagem escolhida. Salve para aplicar.');});}
    catch(e){toast(e.message);}
  });
  $$('[data-upload]',root).forEach(input=>input.onchange=async()=>{
    const file=input.files[0];if(!file)return;if(file.size>8*1024*1024){toast('Use uma foto de até 8 MB.');input.value='';return;}
    input.disabled=true;const buttons=$$('button[type=submit]',root);buttons.forEach(b=>b.disabled=true);
    try{const form=new FormData();form.append('file',file);const result=await api('/api/admin/upload',{method:'POST',body:form});$('[name='+input.dataset.upload+']',root).value=result.url;preview(input.dataset.upload);toast('Foto enviada. Salve para aplicar.');}
    catch(e){toast(e.message);}finally{input.disabled=false;buttons.forEach(b=>b.disabled=false);}
  });
}
// Produtos da mesma categoria que também têm escolhas (ex.: tamanhos P, M, G da marmita do dia).
function groupSiblings(p){return p&&p.category_id?products.filter(x=>x.id!==p.id&&x.category_id===p.category_id&&(x.option_groups||[]).length):[];}
function copyGroupsField(p){
  const list=groupSiblings(p);if(!list.length)return '';
  return '<label class="check-row copy-groups"><span><input type="checkbox" name="copy_groups"> <span>Aplicar estas escolhas também em <b>'+list.length+(list.length===1?' outro produto':' outros produtos')+'</b> desta categoria: '+list.map(x=>esc(x.name)).join(', ')+'</span></span></label><p class="muted small copy-groups-help">Copia as opções de cada grupo com o mesmo nome (ex.: Mistura, Guarnições). O mínimo, o máximo e o preço de cada produto continuam os dele. Deixe desmarcado para mudar só este.</p>';
}
// Leva as opções de cada grupo de origem para o grupo de mesmo nome no outro produto, sem mexer nas regras dele.
function copyGroupOptions(source,target){
  const norm=n=>String(n||'').replace(/\(.*?\)/g,'').trim().toLocaleLowerCase('pt-BR');
  return target.map((tg,i)=>{
    const sg=source.find(g=>norm(g.name)===norm(tg.name))||(source.length===target.length?source[i]:null);
    if(!sg)return {...tg,recipe_share:!!tg.recipe_share};
    const options=sg.options.filter(o=>String(o.name||'').trim()).map(o=>{
      const same=tg.options.find(x=>norm(x.name)===norm(o.name));
      return {...o,id:same?same.id:'o'+crypto.randomUUID().replace(/-/g,'').slice(0,17),unit_cost:same?(same.unit_cost??null):(o.unit_cost??null)};
    });
    return {...tg,recipe_share:!!tg.recipe_share,options:options.length?options:tg.options};
  });
}
async function copyGroupsToSiblings(p,groups){
  const keys=['category_id','name','description','price','image','active','featured','stock','extras','position','unit_cost','low_stock','production_sector'];
  const failed=[];let done=0;
  for(const x of groupSiblings(p)){
    const body=Object.fromEntries(keys.map(k=>[k,x[k]]));body.expected_stock=x.stock;body.option_groups=copyGroupOptions(groups,x.option_groups||[]);
    try{await api('/api/admin/products/'+x.id,{method:'PUT',body:JSON.stringify(body)});done++;}catch(e){failed.push(x.name+': '+e.message);}
  }
  return {done,failed};
}
function productEditor(p=null){
  const d=modal(p?'Editar produto':'Novo produto','<form id="product-form"><div class="form-grid">'+field('name','Nome do produto',p?.name||'','text','required minlength="2" maxlength="120"')+moneyInput('price','Preço',p?.price||0)+'</div><label>Custo do produto (vazio = a informar)<div class="money-input"><span>R$</span><input name="unit_cost" aria-label="Custo do produto" type="number" min="0" step=".01" value="'+(p?.unit_cost==null?'':(p.unit_cost/100).toFixed(2))+'"></div></label>'+field('production_sector','Setor de produção',p?.production_sector||'Cozinha','text','required maxlength="60"')+field('low_stock','Alertar estoque em (unidades)',p?.low_stock??5,'number','min="0" max="1000000" step="1" required')+'<label>Descrição<textarea name="description" maxlength="500" placeholder="Ingredientes e o que torna esse produto especial">'+esc(p?.description||'')+'</textarea></label><div class="form-grid"><label>Categoria<select name="category_id"><option value="">Outros</option>'+categories.map(c=>'<option value="'+c.id+'" '+(p?.category_id===c.id?'selected':'')+'>'+esc(c.name)+'</option>').join('')+'</select></label>'+field('stock','Estoque (vazio = sem controle)',p?.stock??'','number','min="0" step="1"')+'</div>'+uploadField('image','Foto do produto',p?.image||'',true)+'<div class="check-options"><label><input type="checkbox" name="active" '+(!p||p.active?'checked':'')+'> Disponível no cardápio</label><label><input type="checkbox" name="featured" '+(p?.featured?'checked':'')+'> Destaque da casa</label></div><fieldset class="groups-editor"><legend>Escolhas do cliente <small>Tamanho, sabores, molhos, ponto da carne…</small></legend><div id="group-rows"></div><div class="group-templates"><span class="muted">Adicionar:</span><button type="button" class="chip" data-template="size">Tamanho P/M/G</button><button type="button" class="chip" data-template="half">Meio a meio (2 sabores)</button><button type="button" class="chip" data-template="pick1">Escolha 1 (obrigatório)</button><button type="button" class="chip" data-template="blank">Grupo em branco</button></div></fieldset>'+copyGroupsField(p)+'<fieldset><legend>Adicionais opcionais <small>Até 12 opções, cobradas à parte</small></legend><div id="extra-rows"></div><button type="button" id="add-extra" class="text-link">'+icon('plus')+' Adicionar complemento</button></fieldset>'+field('position','Ordem de exibição',p?.position||0,'number','min="0" step="1"')+'<p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Salvar produto</button></form>',true);
  const extras=structuredClone(p?.extras||[]);
  function drawExtras(){
    $('#extra-rows').innerHTML=extras.map((x,i)=>'<div class="extra-row"><input aria-label="Nome do complemento '+(i+1)+'" data-extra-name="'+i+'" placeholder="Ex.: queijo extra" value="'+esc(x.name)+'" maxlength="80" required><input aria-label="Preço do complemento '+(i+1)+'" data-extra-price="'+i+'" type="number" min="0" step=".01" value="'+(x.price/100).toFixed(2)+'" required><input aria-label="Custo do complemento '+(i+1)+'" data-extra-cost="'+i+'" type="number" min="0" step=".01" placeholder="Custo" value="'+(x.unit_cost==null?'':(x.unit_cost/100).toFixed(2))+'"><input aria-label="Quantidade máxima do complemento '+(i+1)+'" data-extra-max="'+i+'" type="number" min="1" max="30" value="'+(x.max_quantity||1)+'"><button type="button" class="icon-btn" data-remove-extra="'+i+'" aria-label="Remover complemento">'+icon('close')+'</button></div>').join('');
    $$('[data-extra-name]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraName)].name=x.value);
    $$('[data-extra-price]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraPrice)].price=cents(x.value));
    $$('[data-extra-max]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraMax)].max_quantity=Number(x.value));
    $$('[data-extra-cost]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraCost)].unit_cost=x.value===''?null:cents(x.value));
    $$('[data-remove-extra]',d).forEach(x=>x.onclick=()=>{extras.splice(Number(x.dataset.removeExtra),1);drawExtras();});
  }
  $('#add-extra').onclick=()=>{if(extras.length>=12)return toast('Use até 12 opções.');extras.push({id:crypto.randomUUID(),name:'',price:0});drawExtras();};drawExtras();bindUploads(d);
  const groups=structuredClone(p?.option_groups||[]);
  const uid=()=>crypto.randomUUID().slice(0,18);
  const opt=(name,price=0)=>({id:uid(),name,price,unit_cost:null});
  const templates={size:()=>({id:uid(),name:'Tamanho',min:1,max:1,pricing:'sum',options:[opt('Pequeno'),opt('Médio',500),opt('Grande',1000)]}),
    half:()=>({id:uid(),name:'Sabores',min:1,max:2,pricing:'max',options:[opt('Sabor 1',0),opt('Sabor 2',0)]}),
    pick1:()=>({id:uid(),name:'Escolha o molho',min:1,max:1,pricing:'sum',options:[opt('Opção 1'),opt('Opção 2')]}),
    blank:()=>({id:uid(),name:'',min:0,max:1,pricing:'sum',options:[opt('')]})};
  function drawGroups(){
    $('#group-rows').innerHTML=groups.map((g,i)=>'<div class="group-card"><div class="group-head"><input aria-label="Nome do grupo '+(i+1)+'" data-g-name="'+i+'" placeholder="Ex.: Tamanho" maxlength="60" value="'+esc(g.name)+'" required><button type="button" class="icon-btn" data-g-remove="'+i+'" aria-label="Remover grupo">'+icon('close')+'</button></div><div class="group-rules"><label>Mínimo<input type="number" min="0" max="30" data-g-min="'+i+'" value="'+g.min+'"></label><label>Máximo<input type="number" min="1" max="30" data-g-max="'+i+'" value="'+g.max+'"></label><label>Cobrança<select data-g-pricing="'+i+'"><option value="sum" '+(g.pricing==='sum'?'selected':'')+'>Soma as opções</option><option value="max" '+(g.pricing==='max'?'selected':'')+'>Cobra a mais cara (meio a meio)</option><option value="average" '+(g.pricing==='average'?'selected':'')+'>Média dos sabores</option></select></label></div><label class="check-row"><span><input type="checkbox" data-g-share="'+i+'" '+(g.recipe_share?'checked':'')+'> Dividir o consumo da receita entre os sabores escolhidos</span></label><p class="muted group-explain">'+(g.min?'Obrigatório: o cliente precisa escolher '+(g.min===g.max?g.min:'de '+g.min+' a '+g.max)+'.':'Opcional: até '+g.max+'.')+'</p>'+g.options.map((o,j)=>'<div class="extra-row"><input aria-label="Opção '+(j+1)+' do grupo '+(i+1)+'" data-o-name="'+i+'.'+j+'" placeholder="Nome da opção" maxlength="80" value="'+esc(o.name)+'" required><input aria-label="Preço da opção" data-o-price="'+i+'.'+j+'" type="number" min="0" step=".01" value="'+(o.price/100).toFixed(2)+'"><input aria-label="Custo da opção" data-o-cost="'+i+'.'+j+'" type="number" min="0" step=".01" placeholder="Custo" value="'+(o.unit_cost==null?'':(o.unit_cost/100).toFixed(2))+'"><input aria-label="Quantidade máxima da opção" data-o-max="'+i+'.'+j+'" type="number" min="1" max="30" value="'+(o.max_quantity||1)+'"><button type="button" class="icon-btn" data-o-remove="'+i+'.'+j+'" aria-label="Remover opção">'+icon('close')+'</button></div>').join('')+'<button type="button" class="text-link" data-o-add="'+i+'">'+icon('plus')+' Adicionar opção</button></div>').join('')+(groups.some(g=>g.min)?'<p class="notice">Com escolha obrigatória, o preço do produto pode ser R$ 0,00: o cliente paga o valor das opções (ex.: tamanho). No cardápio aparece “a partir de”.</p>':'');
    const at=k=>k.split('.').map(Number);
    $$('[data-g-name]',d).forEach(x=>x.oninput=()=>groups[Number(x.dataset.gName)].name=x.value);
    $$('[data-g-min]',d).forEach(x=>x.onchange=()=>{groups[Number(x.dataset.gMin)].min=Math.max(0,Number(x.value)||0);drawGroups();});
    $$('[data-g-max]',d).forEach(x=>x.onchange=()=>{groups[Number(x.dataset.gMax)].max=Math.max(1,Number(x.value)||1);drawGroups();});
    $$('[data-g-share]',d).forEach(x=>x.onchange=()=>groups[Number(x.dataset.gShare)].recipe_share=x.checked);
    $$('[data-g-pricing]',d).forEach(x=>x.onchange=()=>groups[Number(x.dataset.gPricing)].pricing=x.value);
    $$('[data-g-remove]',d).forEach(x=>x.onclick=()=>{groups.splice(Number(x.dataset.gRemove),1);drawGroups();});
    $$('[data-o-name]',d).forEach(x=>x.oninput=()=>{const [i,j]=at(x.dataset.oName);groups[i].options[j].name=x.value;});
    $$('[data-o-price]',d).forEach(x=>x.oninput=()=>{const [i,j]=at(x.dataset.oPrice);groups[i].options[j].price=cents(x.value||0);});
    $$('[data-o-max]',d).forEach(x=>x.oninput=()=>{const [i,j]=at(x.dataset.oMax);groups[i].options[j].max_quantity=Number(x.value);});
    $$('[data-o-cost]',d).forEach(x=>x.oninput=()=>{const [i,j]=at(x.dataset.oCost);groups[i].options[j].unit_cost=x.value===''?null:cents(x.value);});
    $$('[data-o-remove]',d).forEach(x=>x.onclick=()=>{const [i,j]=at(x.dataset.oRemove);if(groups[i].options.length===1)return toast('O grupo precisa de pelo menos uma opção.');groups[i].options.splice(j,1);drawGroups();});
    $$('[data-o-add]',d).forEach(x=>x.onclick=()=>{const g=groups[Number(x.dataset.oAdd)];if(g.options.length>=30)return toast('Use até 30 opções por grupo.');g.options.push(opt(''));drawGroups();});
  }
  $$('[data-template]',d).forEach(b=>b.onclick=()=>{if(groups.length>=10)return toast('Use até 10 grupos.');const first=!groups.some(g=>g.min);groups.push(templates[b.dataset.template]());drawGroups();if(first&&['size','half'].includes(b.dataset.template))$('[name=price]',d).value='0.00';});
  drawGroups();
  $('[name=price]',d).min='0';
  bindForm($('#product-form'),async form=>{
    const value={production_sector:form.get('production_sector'),expected_stock:p?.stock??null,unit_cost:form.get('unit_cost')===''?null:cents(form.get('unit_cost')),low_stock:Number(form.get('low_stock')),name:form.get('name'),description:form.get('description'),price:cents(form.get('price')),category_id:form.get('category_id')?Number(form.get('category_id')):null,stock:form.get('stock')===''?null:Number(form.get('stock')),image:form.get('image'),active:form.has('active'),featured:form.has('featured'),position:Number(form.get('position')),extras,option_groups:groups.map(g=>({...g,min:g.min,max:g.max}))};
    await api('/api/admin/products'+(p?'/'+p.id:''),{method:p?'PUT':'POST',body:JSON.stringify(value)});
    let message='Produto salvo.';
    if(p&&form.has('copy_groups')){const r=await copyGroupsToSiblings({...p,category_id:value.category_id},value.option_groups);message='Produto salvo e escolhas copiadas para '+r.done+(r.done===1?' produto.':' produtos.');if(r.failed.length)message+=' Não copiou em: '+r.failed.join('; ');}
    closeModal();toast(message);await switchTab('products');
  });
}
function importDialog(){
  modal('Importar cardápio por planilha','<ol class="steps"><li><a class="text-link" href="/api/admin/products/template" download>'+icon('copy')+' Baixe o modelo (.xlsx)</a></li><li>Preencha uma linha por produto: categoria, nome, descrição, preço, foto (link https), estoque e destaque (sim).</li><li>Envie a planilha (.xlsx ou .csv). Os produtos entram no cardápio; depois dá para colocar fotos e variações.</li></ol><form id="import-form"><label>Planilha<input type="file" name="file" accept=".xlsx,.csv" required></label><p class="form-error" role="alert" hidden></p><div id="import-result"></div><button class="btn full" type="submit">Importar produtos</button></form>');
  bindForm($('#import-form'),async form=>{const r=await api('/api/admin/products/import',{method:'POST',body:form});
    $('#import-result').innerHTML='<div class="notice"><b>'+r.created+' produto'+(r.created===1?'':'s')+' importado'+(r.created===1?'':'s')+'.</b>'+(r.skipped.length?'<p>Linhas não importadas:</p><ul>'+r.skipped.map(x=>'<li>Linha '+x.line+': '+esc(x.error)+'</li>').join('')+'</ul>':'')+'</div>';
    toast(r.created+' produtos importados.');const result=await api('/api/admin/products');products=result.products;categories=result.categories;});
  $('#modal').addEventListener('close',()=>{if(tab==='products')switchTab('products');},{once:true});
}
function categoriesDialog(){
  const d=modal('Categorias do cardápio','<div class="category-list">'+categories.map(c=>'<div><b>'+esc(c.name)+'</b><button data-delete-category="'+c.id+'" class="icon-btn" aria-label="Remover categoria '+esc(c.name)+'">'+icon('close')+'</button></div>').join('')+'</div><form id="category-form">'+field('name','Nova categoria','','text','required maxlength="80"')+'<p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Adicionar categoria</button></form><p class="muted">Ao remover uma categoria, seus produtos ficam em Outros.</p>');
  bindForm($('#category-form'),async form=>{await api('/api/admin/categories',{method:'POST',body:JSON.stringify({name:form.get('name')})});const result=await api('/api/admin/products');categories=result.categories;products=result.products;categoriesDialog();productsPage();});
  $$('[data-delete-category]',d).forEach(b=>b.onclick=async()=>{try{await api('/api/admin/categories/'+b.dataset.deleteCategory,{method:'DELETE'});const result=await api('/api/admin/products');categories=result.categories;products=result.products;categoriesDialog();productsPage();}catch(e){toast(e.message);}});
}
async function couponsPage(){
  try{
    const {coupons}=await api('/api/admin/coupons');
    $('#dashboard-content').innerHTML='<div class="page-toolbar"><div class="chips"><button class="chip" id="catalog-tab">Produtos</button><button class="chip active">Cupons</button></div><button class="btn" id="new-coupon">'+icon('plus')+' Novo cupom</button></div><div class="coupon-grid">'+(coupons.length?coupons.map(c=>'<article class="panel coupon"><span class="feature-icon">'+icon('tag')+'</span><h2>'+esc(c.code)+'</h2><strong>'+ (c.kind==='percent'?c.value+'% OFF':money(c.value)+' OFF')+'</strong><p>Pedido mínimo: '+money(c.minimum)+'</p><p>Validade: '+(c.expires?esc(c.expires.split('-').reverse().join('/')):'Sem data limite')+'</p><p>'+c.uses+' usos'+(c.max_uses?' de '+c.max_uses:'')+'</p><button class="btn '+(c.active?'secondary':'')+'" data-toggle-coupon="'+c.id+'" data-active="'+c.active+'">'+(c.active?'Pausar cupom':'Ativar cupom')+'</button></article>').join(''):empty('Uma boa oferta aproxima','Crie um cupom e compartilhe com seus clientes.'))+'</div>';
    $('#catalog-tab').onclick=productsPage;$('#new-coupon').onclick=couponEditor;
    $$('[data-toggle-coupon]').forEach(b=>b.onclick=async()=>{try{await api('/api/admin/coupons/'+b.dataset.toggleCoupon,{method:'PATCH',body:JSON.stringify({active:!Number(b.dataset.active)})});couponsPage();}catch(e){toast(e.message);}});
  }catch(e){toast(e.message);}
}
function couponEditor(){
  modal('Novo cupom','<form id="coupon-form">'+field('code','Código do cupom','','text','required minlength="3" maxlength="30" pattern="[A-Za-z0-9_-]+" placeholder="BEMVINDO10"')+'<div class="form-grid"><label>Tipo<select name="kind"><option value="percent">Percentual (%)</option><option value="fixed">Valor em reais (R$)</option></select></label>'+field('value','Desconto','','number','required min="0.01" step=".01"')+'</div>'+moneyInput('minimum','Pedido mínimo em produtos')+'<div class="form-grid">'+field('expires','Validade (opcional)','','date')+field('max_uses','Limite de usos (opcional)','','number','min="1" step="1"')+'</div><label class="check-row"><span><input type="checkbox" name="first_order"> Só para a primeira compra (o cliente informa o WhatsApp)</span></label><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Criar cupom</button></form>');
  bindForm($('#coupon-form'),async form=>{await api('/api/admin/coupons',{method:'POST',body:JSON.stringify({code:form.get('code').toUpperCase(),kind:form.get('kind'),value:form.get('kind')==='fixed'?cents(form.get('value')):Number(form.get('value')),minimum:cents(form.get('minimum')),expires:form.get('expires'),max_uses:form.get('max_uses')?Number(form.get('max_uses')):null,first_order:form.has('first_order')})});closeModal();toast('Cupom criado.');couponsPage();});
}
function driversPage(){
  const delivery=orders.filter(o=>o.mode==='delivery'&&!['completed','cancelled'].includes(o.status));
  $('#dashboard-content').innerHTML='<div class="page-toolbar"><p class="muted">'+delivery.length+' entregas em andamento</p><button class="btn" id="new-driver">'+icon('plus')+' Novo entregador</button></div><div class="driver-grid">'+(drivers.length?drivers.map(d=>'<article class="panel"><div class="driver-head"><span class="feature-icon">'+icon('truck')+'</span><span class="badge '+(d.active?'green':'gray')+'">'+(d.active?'Disponível':'Inativo')+'</span></div><h2>'+esc(d.name)+'</h2><p>'+esc(d.phone||'Sem telefone cadastrado')+'</p><p class="muted">'+delivery.filter(o=>o.driver_id===d.id).length+' pedidos atribuídos</p><button class="btn secondary full" data-edit-driver="'+d.id+'">'+icon('edit')+' Editar entregador</button></article>').join(''):empty('Uma equipe mais próxima','Cadastre os entregadores e atribua cada pedido pelo painel.'))+'</div><section class="panel"><div class="section-heading"><h2>Pedidos para entrega</h2><span class="muted">Clique para atribuir um entregador.</span></div><div class="history-grid">'+(delivery.length?delivery.map(orderCard).join(''):empty('Nenhuma entrega pendente','Os pedidos de entrega aparecem aqui.'))+'</div></section>';
  $('#new-driver').onclick=()=>driverEditor();$$('[data-edit-driver]').forEach(b=>b.onclick=()=>driverEditor(drivers.find(d=>d.id===Number(b.dataset.editDriver))));bindOrderButtons();
}
function driverEditor(driver=null){
  modal(driver?'Editar entregador':'Novo entregador','<form id="driver-form">'+field('name','Nome',driver?.name||'','text','required minlength="2" maxlength="100"')+field('phone','Telefone',driver?.phone||'','tel','maxlength="20"')+'<label class="check-row"><span><input name="active" type="checkbox" '+(!driver||driver.active?'checked':'')+'> Disponível para entregas</span></label><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Salvar entregador</button></form>');
  bindForm($('#driver-form'),async form=>{await api('/api/admin/drivers'+(driver?'/'+driver.id:''),{method:driver?'PUT':'POST',body:JSON.stringify({name:form.get('name'),phone:form.get('phone'),active:form.has('active')})});closeModal();toast('Entregador salvo.');switchTab('drivers');});
}
function salesPage(summary){
  $('#dashboard-content').innerHTML='<div class="page-toolbar"><div class="chips">'+[[1,'Hoje'],[7,'7 dias'],[30,'30 dias']].map(([value,label])=>'<button class="chip '+(period===value?'active':'')+'" data-period="'+value+'">'+label+'</button>').join('')+'</div><div class="toolbar-actions"><button class="btn secondary" id="report-button">'+icon('print')+' Relatório PDF / Excel</button><a class="btn secondary" href="/api/admin/export">'+icon('chart')+' Pedidos CSV</a><button class="btn" id="new-expense">'+icon('plus')+' Nova despesa</button></div></div><div class="metrics four">'+metric('Vendas concluídas',money(summary.revenue),'chart')+metric('Recebido',money(summary.received),'wallet')+metric('Despesas',money(summary.expenses_total),'wallet')+metric('Saldo de recebimentos',money(summary.balance),'wallet')+'</div><div class="sales-grid"><section class="panel"><div class="section-heading"><h2>Vendas do período</h2><span>'+summary.completed+' concluídos</span></div>'+chart(summary.chart)+'</section><section class="panel"><h2>Por forma de pagamento</h2>'+summary.payments.map(p=>'<div class="payment-line"><span>'+pay[p.method]+'</span><strong>'+money(p.total)+'</strong></div>').join('')+'<div class="notice"><div>Aguardando pagamento <b>'+money(summary.pending_payment)+'</b></div><small>Vendas consideram pedidos concluídos. Recebimentos consideram os pagamentos confirmados, inclusive pedidos em andamento.</small></div></section></div><section class="panel"><div class="section-heading"><h2>Despesas registradas</h2><span class="muted">'+summary.expenses.length+' lançamentos</span></div>'+(summary.expenses.length?'<div class="table-wrap"><table><thead><tr><th>Descrição</th><th>Data</th><th>Valor</th><th><span class="sr-only">Ações</span></th></tr></thead><tbody>'+summary.expenses.map(e=>'<tr><td>'+esc(e.description)+'</td><td>'+date(e.created_at)+'</td><td>'+money(e.amount)+'</td><td><button class="icon-btn" data-delete-expense="'+e.id+'" aria-label="Excluir despesa">'+icon('close')+'</button></td></tr>').join('')+'</tbody></table></div>':empty('Nenhuma despesa no período','Registre os gastos para acompanhar o saldo.'))+'</section>';
  $$('[data-period]').forEach(b=>b.onclick=()=>{period=Number(b.dataset.period);switchTab('sales');});
  $('#new-expense').onclick=expenseEditor;
  $('#report-button').onclick=reportDialog;
  $$('[data-delete-expense]').forEach(b=>b.onclick=()=>{modal('Excluir esta despesa?','<p>O lançamento será removido do período.</p><button id="confirm-delete" class="btn danger full">Excluir despesa</button>');$('#confirm-delete').onclick=async()=>{try{await api('/api/admin/expenses/'+b.dataset.deleteExpense,{method:'DELETE'});closeModal();switchTab('sales');}catch(e){toast(e.message);}};});
}
function expenseEditor(){
  modal('Nova despesa','<form id="expense-form">'+field('description','Descrição','','text','required minlength="2" maxlength="200"')+moneyInput('amount','Valor')+'<label>Categoria<select name="category"><option value="operating">Despesa operacional</option><option value="inventory">Compra de estoque</option></select></label><p class="muted">Compras de estoque afetam o caixa. O lucro usa o custo dos produtos vendidos, para não descontar a compra duas vezes.</p><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Registrar despesa</button></form>');
  bindForm($('#expense-form'),async form=>{await api('/api/admin/expenses',{method:'POST',body:JSON.stringify({description:form.get('description'),amount:cents(form.get('amount')),category:form.get('category')})});closeModal();toast('Despesa registrada.');switchTab('sales');});
}
function settingsPage(){
  if(!['owner','manager'].includes(role)){
    $('#dashboard-content').innerHTML=alertsPanel()+'<section class="panel"><h2>Sua conta</h2><p class="muted">Você entra como <b>'+esc(roleLabel)+'</b> na loja '+esc(store.name)+'. As configurações da loja ficam com o dono.</p><button id="change-password" class="btn secondary" type="button">Alterar minha senha</button></section>';
    $('#change-password').onclick=passwordDialog;bindAlertsPanel();return;
  }
  $('#dashboard-content').innerHTML='<form id="store-form"><section class="panel"><div class="section-heading"><div><h2>Identidade da loja</h2><p class="muted">A marca que seus clientes conhecem.</p></div><span class="feature-icon">'+icon('store')+'</span></div><div class="form-grid">'+field('name','Nome do comércio',store.name,'text','required minlength="2" maxlength="100"')+field('color','Cor principal',store.color,'color')+'</div><label>Descrição<textarea name="description" maxlength="500">'+esc(store.description)+'</textarea></label><div class="form-grid">'+uploadField('logo','Logo',store.logo)+uploadField('banner','Capa do cardápio',store.banner)+'</div><div class="notice">Seu link: <b>'+esc(location.origin+'/loja/'+store.slug)+'</b> <button class="text-link" type="button" id="settings-copy">'+icon('copy')+' Copiar</button></div></section><section class="panel"><h2>Contato e entrega</h2><div class="form-grid">'+field('phone','WhatsApp com DDD',store.phone,'tel','maxlength="20"')+field('delivery_minutes','Estimativa de entrega',store.delivery_minutes,'text','required maxlength="40"')+'</div><label>Endereço da loja<textarea name="address" maxlength="400">'+esc(store.address)+'</textarea></label><div class="form-grid">'+moneyInput('delivery_fee','Taxa de entrega',store.delivery_fee)+moneyInput('minimum_order','Pedido mínimo em produtos',store.minimum_order)+'</div></section><section class="panel"><div class="section-heading"><div><h2>Taxa por bairro</h2><p class="muted">Opcional. Com bairros cadastrados, o cliente escolhe o bairro e a taxa é calculada sozinha. Sem bairros, vale a taxa única acima.</p></div><span class="feature-icon">'+icon('truck')+'</span></div><div id="zone-rows" class="zone-rows">'+store.delivery_zones.map(zoneRow).join('')+'</div><button id="add-zone" class="btn secondary small" type="button">'+icon('plus')+' Adicionar bairro</button></section><section class="panel"><div class="section-heading"><div><h2>Horário de funcionamento</h2><p class="muted">A loja abre e fecha sozinha nesses horários. O botão Loja aberta/fechada continua valendo para fechar na hora que precisar.</p></div><span class="feature-icon">'+icon('clock')+'</span></div><label class="check-row"><span><input name="auto_hours" type="checkbox" '+(store.auto_hours?'checked':'')+'> Abrir e fechar automaticamente nestes horários</span></label><label class="check-row"><span><input name="allow_scheduling" type="checkbox" '+(store.allow_scheduling?'checked':'')+'> Aceitar pedidos agendados (até 7 dias, só dentro do horário)</span></label><div class="hours-editor">'+days.map((name,i)=>{const shifts=store.hours[String(i)]||[];const a=shifts[0]||['18:00','23:00'],b=shifts[1]||['',''];return '<div class="hours-row"><label class="check-row"><span><input type="checkbox" data-day="'+i+'" '+(shifts.length?'checked':'')+'> '+name+'</span></label><div class="hours-shifts"><input type="time" aria-label="'+name+': abre" data-start="'+i+'" value="'+a[0]+'"><span>às</span><input type="time" aria-label="'+name+': fecha" data-end="'+i+'" value="'+a[1]+'"><span class="muted">e</span><input type="time" aria-label="'+name+': abre no 2º turno" data-start2="'+i+'" value="'+b[0]+'"><span>às</span><input type="time" aria-label="'+name+': fecha no 2º turno" data-end2="'+i+'" value="'+b[1]+'"></div></div>';}).join('')+'</div><p class="muted">O 2º turno é opcional (ex.: almoço e jantar). Para virar a madrugada, use por exemplo 18:00 às 02:00.</p></section><section class="panel qr-panel"><div><h2>QR Code do cardápio</h2><p class="muted">Imprima e coloque no balcão, nas mesas, na sacola de entrega e no panfleto. O cliente aponta a câmera e cai direto no seu cardápio.</p><div class="qr-actions"><a class="btn" href="/api/admin/qrcode?format=png&amp;download=1">'+icon('print')+' Baixar para imprimir</a><a class="btn secondary" href="/api/admin/qrcode?download=1">Baixar em SVG</a></div></div><img src="/api/admin/qrcode" alt="QR Code que abre o cardápio da loja" width="180" height="180"></section><section class="panel"><div class="section-heading"><div><h2>Cartão fidelidade</h2><p class="muted">O cliente é reconhecido pelo WhatsApp. A cada X pedidos concluídos, o desconto entra sozinho no próximo.</p></div><span class="feature-icon">'+icon('tag')+'</span></div><label class="check-row"><span><input name="loyalty_enabled" type="checkbox" '+(store.loyalty_enabled?'checked':'')+'> Ativar cartão fidelidade</span></label><div class="form-grid">'+field('loyalty_goal','Pedidos para ganhar o prêmio',store.loyalty_goal,'number','min="2" max="100" step="1" required')+moneyInput('loyalty_reward','Valor do prêmio (desconto)',store.loyalty_reward)+'</div></section><section class="panel"><h2>Pagamentos</h2><p class="muted">Escolha como seu cliente pode pagar. As opções online são confirmadas pelo Mercado Pago; dinheiro e cartão na entrega são conferidos pela loja.</p><div class="check-options">'+Object.entries(pay).filter(([value])=>value!=='credit').map(([value,label])=>'<label><input name="payments" type="checkbox" value="'+value+'" '+(store.payments.includes(value)?'checked':'')+' '+(['pix_online','card_online'].includes(value)&&!store.mp_connected?'disabled':'')+'> '+label+'</label>').join('')+'</div><div class="notice"><b>Pix e cartão online (Mercado Pago)</b><p>'+(store.mp_connected?'Conectado como <b>'+esc(store.mp_account)+'</b>. Os pagamentos dos pedidos chegam à conta da sua loja. A mensalidade do sistema é cobrada separadamente. <button type="button" class="text-link" id="mp-disconnect">Desconectar</button>':'No Mercado Pago: Seu negócio › Configurações › Credenciais › copie o <b>Access Token de produção</b> e cole aqui.')+'</p>'+(store.mp_connected?'':'<div class="inline-input"><input id="mp-token" type="password" autocomplete="off" placeholder="APP_USR-..." aria-label="Access Token do Mercado Pago"><button type="button" class="btn secondary" id="mp-connect">Conectar</button></div>')+'</div>'+field('pix_key','Chave Pix',store.pix_key,'text','maxlength="200"')+'</section><p class="form-error" role="alert" hidden></p><div class="settings-save"><button class="btn" type="submit">Salvar configurações '+icon('check')+'</button><button id="change-password" class="btn secondary" type="button">Alterar senha</button></div></form>';
  if($('#mp-connect'))$('#mp-connect').onclick=async()=>{try{const r=await api('/api/admin/payments/mercadopago',{method:'PUT',body:JSON.stringify({access_token:$('#mp-token').value.trim()})});toast('Mercado Pago conectado: '+r.account);store=(await api('/api/admin/store')).store;settingsPage();}catch(e){toast(e.message);}};
  if($('#mp-disconnect'))$('#mp-disconnect').onclick=async()=>{try{await api('/api/admin/payments/mercadopago',{method:'DELETE'});store=(await api('/api/admin/store')).store;toast('Mercado Pago desconectado.');settingsPage();}catch(e){toast(e.message);}};
  bindUploads($('#store-form'));$('#settings-copy').onclick=()=>copy(location.origin+'/loja/'+store.slug);$('#change-password').onclick=passwordDialog;
  $('#dashboard-content').insertAdjacentHTML('afterbegin',planPanel()+alertsPanel());bindAlertsPanel();bindPlanPanel();
  if(role==='owner'){$('#dashboard-content').insertAdjacentHTML('afterbegin','<section class="panel" id="team-panel"><div class="loading small-loading">Carregando equipe…</div></section>');teamPanel();}
  const bindZones=()=>$$('[data-remove-zone]').forEach(b=>b.onclick=()=>b.closest('.zone-row').remove());bindZones();
  $('#add-zone').onclick=()=>{$('#zone-rows').insertAdjacentHTML('beforeend',zoneRow({name:'',fee:store.delivery_fee}));bindZones();$('#zone-rows .zone-row:last-child input').focus();};
  bindForm($('#store-form'),async form=>{
    const value={...store,name:form.get('name'),description:form.get('description'),phone:form.get('phone'),address:form.get('address'),delivery_minutes:form.get('delivery_minutes'),color:form.get('color'),logo:form.get('logo'),banner:form.get('banner'),delivery_fee:cents(form.get('delivery_fee')),minimum_order:cents(form.get('minimum_order')),payments:form.getAll('payments'),pix_key:form.get('pix_key'),auto_hours:form.has('auto_hours'),allow_scheduling:form.has('allow_scheduling'),loyalty_enabled:form.has('loyalty_enabled'),loyalty_goal:Number(form.get('loyalty_goal')),loyalty_reward:cents(form.get('loyalty_reward')),hours:collectHours(),delivery_zones:$$('#zone-rows .zone-row').map(r=>({name:$('[data-zone-name]',r).value.trim(),fee:cents($('[data-zone-fee]',r).value||0)})).filter(z=>z.name)};
    store=(await api('/api/admin/store',{method:'PUT',body:JSON.stringify(value)})).store;toast('Sua loja foi atualizada.');updateStoreButton();
  });
}
const roleInfo={manager:['Gerente','Tudo, menos equipe, integrações e taxas'],cashier:['Caixa','Pedidos, balcão, clientes, entregas e vendas'],kitchen:['Cozinha','Só a fila de produção e o avanço dos pedidos']};
async function teamPanel(){
  const el=$('#team-panel');if(!el)return;
  try{
    const {members}=await api('/api/admin/team');
    el.innerHTML='<div class="section-heading"><div><h2>Equipe</h2><p class="muted">Cada pessoa entra com o próprio e-mail e senha e só vê o que a função permite.</p></div><button type="button" id="add-member" class="btn">'+icon('plus')+' Adicionar pessoa</button></div>'+
      (members.length?'<div class="team-list">'+members.map(m=>'<article class="team-card '+(m.active?'':'inactive')+'"><span class="avatar">'+esc(m.name.split(' ').slice(0,2).map(x=>x[0]).join('').toUpperCase())+'</span><div><b>'+esc(m.name)+'</b><small class="muted">'+esc(m.email)+' • '+(m.last_login_at?'último acesso '+date(m.last_login_at):'ainda não entrou')+'</small></div><select data-member-role="'+m.id+'" aria-label="Função de '+esc(m.name)+'">'+Object.entries(roleInfo).map(([k,[l]])=>'<option value="'+k+'" '+(k===m.role?'selected':'')+'>'+l+'</option>').join('')+'</select><div class="row-actions"><button type="button" class="btn secondary small" data-member-pass="'+m.id+'">Nova senha</button><button type="button" class="btn secondary small '+(m.active?'danger-text':'')+'" data-member-active="'+m.id+'" data-value="'+(m.active?0:1)+'">'+(m.active?'Desativar':'Reativar')+'</button></div></article>').join('')+'</div>':'<p class="muted">Ainda não há ninguém além de você. Adicione o caixa, a cozinha ou um gerente.</p>')+
      '<div class="role-legend">'+Object.values(roleInfo).map(([l,d])=>'<span><b>'+l+':</b> '+d+'</span>').join('')+'</div>';
    $('#add-member').onclick=()=>{modal('Adicionar pessoa à equipe','<form id="member-form">'+field('name','Nome','','text','required minlength="2" maxlength="100"')+field('email','E-mail de acesso','','email','required maxlength="254"')+field('password','Senha inicial (mín. 10 caracteres)','','text','required minlength="10" maxlength="128" autocomplete="new-password"')+'<label>Função<select name="role">'+Object.entries(roleInfo).map(([k,[l,d]])=>'<option value="'+k+'" '+(k==='cashier'?'selected':'')+'>'+l+' — '+d+'</option>').join('')+'</select></label><p class="muted">Passe o e-mail e a senha para a pessoa. Ela pode trocar a senha depois em Configurações.</p><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Adicionar</button></form>');
      bindForm($('#member-form'),async f=>{await api('/api/admin/team',{method:'POST',body:JSON.stringify(Object.fromEntries(f))});closeModal();toast('Pessoa adicionada à equipe.');teamPanel();});};
    $$('[data-member-role]').forEach(s=>s.onchange=async()=>{try{await api('/api/admin/team/'+s.dataset.memberRole,{method:'PATCH',body:JSON.stringify({role:s.value})});toast('Função atualizada. A pessoa precisa entrar de novo.');}catch(e){toast(e.message);teamPanel();}});
    $$('[data-member-active]').forEach(b=>b.onclick=async()=>{try{await api('/api/admin/team/'+b.dataset.memberActive,{method:'PATCH',body:JSON.stringify({active:b.dataset.value==='1'})});toast(b.dataset.value==='1'?'Acesso reativado.':'Acesso desativado na hora.');teamPanel();}catch(e){toast(e.message);}});
    $$('[data-member-pass]').forEach(b=>b.onclick=()=>{modal('Definir nova senha','<form id="member-pass">'+field('password','Nova senha (mín. 10 caracteres)','','text','required minlength="10" maxlength="128" autocomplete="new-password"')+'<p class="muted">A pessoa sai de todos os aparelhos e entra com a senha nova.</p><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Salvar senha</button></form>');bindForm($('#member-pass'),async f=>{await api('/api/admin/team/'+b.dataset.memberPass+'/password',{method:'POST',body:JSON.stringify({password:f.get('password')})});closeModal();toast('Senha alterada.');});});
  }catch(e){el.innerHTML='<p class="form-error">'+esc(e.message)+'</p>';}
}
function zoneRow(z){return '<div class="zone-row"><input data-zone-name aria-label="Nome do bairro" placeholder="Nome do bairro" maxlength="60" value="'+esc(z.name)+'"><div class="money-input"><span>R$</span><input data-zone-fee aria-label="Taxa do bairro" type="number" min="0" step="0.01" value="'+(z.fee/100).toFixed(2)+'"></div><button type="button" class="icon-btn" data-remove-zone aria-label="Remover bairro">'+icon('close')+'</button></div>';}
function collectHours(){
  const hours={};
  days.forEach((_,i)=>{if(!$('[data-day="'+i+'"]').checked)return;const shifts=[];
    const a=$('[data-start="'+i+'"]').value,b=$('[data-end="'+i+'"]').value,c=$('[data-start2="'+i+'"]').value,d=$('[data-end2="'+i+'"]').value;
    if(!a||!b)throw new Error('Informe abertura e fechamento de '+days[i]+'.');shifts.push([a,b]);
    if(c&&d)shifts.push([c,d]);else if(c||d)throw new Error('Complete o 2º turno de '+days[i]+'.');hours[String(i)]=shifts;});
  return hours;
}
function reportDialog(){
  const month=new Date().toISOString().slice(0,7);
  modal('Baixar relatório','<form id="report-form"><label>Período<select name="period" aria-label="Período"><option value="days=1">Hoje</option><option value="days=7">Últimos 7 dias</option><option value="days=30" selected>Últimos 30 dias</option><option value="days=90">Últimos 90 dias</option><option value="days=365">Último ano</option><option value="month">Um mês específico</option></select></label><label id="report-month" class="hidden">Mês<input type="month" name="month" value="'+month+'" max="'+month+'"></label><p class="muted">O relatório traz resumo, vendas por dia, formas de pagamento, produtos mais vendidos, todos os pedidos e as despesas.</p><div class="report-actions"><a class="btn" id="report-pdf" download>'+icon('print')+' Baixar PDF</a><a class="btn secondary" id="report-xlsx" download>'+icon('chart')+' Baixar Excel</a></div></form>');
  const form=$('#report-form');
  const update=()=>{const choice=form.period.value;$('#report-month').classList.toggle('hidden',choice!=='month');const query=choice==='month'?'month='+(form.month.value||month):choice;$('#report-pdf').href='/api/admin/report?format=pdf&'+query;$('#report-xlsx').href='/api/admin/report?format=xlsx&'+query;};
  form.period.onchange=update;form.month.onchange=update;update();
}
function passwordDialog(){
  modal('Alterar sua senha','<form id="password-form">'+field('current_password','Senha atual','','password','required autocomplete="current-password"')+field('new_password','Nova senha','','password','required minlength="10" maxlength="128" autocomplete="new-password"')+'<p class="muted">As outras sessões serão encerradas.</p><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Alterar senha</button></form>');
  bindForm($('#password-form'),async form=>{await api('/api/auth/password',{method:'PUT',body:JSON.stringify(Object.fromEntries(form))});closeModal();toast('Senha alterada.');});
}

let kitchenSector='';
function kitchenPage(){
 const active=orders.filter(o=>['new','preparing','ready'].includes(o.status)),sectors=[...new Set(active.flatMap(o=>o.items.map(i=>i.production_sector||'Cozinha')))];
 const list=active.filter(o=>!kitchenSector||o.items.some(i=>(i.production_sector||'Cozinha')===kitchenSector));
 $('#dashboard-content').innerHTML='<div class="page-toolbar"><span class="badge green">'+list.length+' pedidos na produção</span><label>Setor<select id="kitchen-sector" aria-label="Setor da cozinha"><option value="">Todos os setores</option>'+sectors.map(sector=>'<option '+(sector===kitchenSector?'selected':'')+'>'+esc(sector)+'</option>').join('')+'</select></label><button id="kitchen-refresh" class="btn secondary">Atualizar fila</button></div><div class="kitchen-grid">'+list.map(o=>'<article class="panel kitchen-ticket"><div class="section-heading"><h2>#'+o.number+'</h2><span class="badge">'+statuses[o.status]+'</span></div><small>'+date(o.created_at)+' • '+(o.mode==='delivery'?'Entrega':'Retirada')+'</small>'+o.items.filter(i=>!kitchenSector||(i.production_sector||'Cozinha')===kitchenSector).map(i=>'<div class="kitchen-item"><span class="badge gray">'+esc(i.production_sector||'Cozinha')+'</span><b>'+i.quantity+' × '+esc(i.name)+'</b><p>'+i.extras.map(x=>esc(x.name)).join(', ')+'</p>'+(i.notes?'<p class="notice">'+esc(i.notes)+'</p>':'')+(i.kitchen_state==='ready'?'<span class="badge green">Item pronto</span>':'<button class="btn secondary small" data-kitchen-item="'+i.id+'" data-state="'+(i.kitchen_state==='preparing'?'ready':'preparing')+'">'+(i.kitchen_state==='preparing'?'Concluir item':'Preparar item')+'</button>')+'</div>').join('')+(o.notes?'<p class="notice">'+esc(o.notes)+'</p>':'')+'<button class="btn secondary small" data-kitchen-print="'+o.id+'">Imprimir setor</button>'+(o.status==='ready'?'<span class="badge green">Aguardando expedição</span>':!kitchenSector?'<button class="btn full" data-next="'+o.id+'">'+actionLabel(o)+'</button>':'')+'</article>').join('')+'</div>'+(!list.length?empty('Cozinha em dia','Novos pedidos e itens em preparo aparecem aqui.'): '');
 $('#kitchen-sector').onchange=e=>{kitchenSector=e.target.value;kitchenPage();};$('#kitchen-refresh').onclick=()=>switchTab('kitchen');bindOrderButtons();
 $$('[data-kitchen-item]').forEach(b=>b.onclick=async()=>{try{await api('/api/admin/order-items/'+b.dataset.kitchenItem+'/kitchen',{method:'PATCH',body:JSON.stringify({state:b.dataset.state})});switchTab('kitchen');}catch(e){toast(e.message);}});
 $$('[data-kitchen-print]').forEach(b=>b.onclick=()=>printTicket(orders.find(o=>o.id===Number(b.dataset.kitchenPrint)),'sector:'+kitchenSector));
}
