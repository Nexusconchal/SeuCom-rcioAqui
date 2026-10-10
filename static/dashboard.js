import { managementView, costsDialog, manualOrder, overviewDetails } from './management.js';
import { $, $$, icon, brand, money, esc, image, api, auth, modal, closeModal, bindForm, empty, toast, pay, date, attachFallbacks, copy, cents, field, moneyInput, statuses } from './ui.js';
let store, products=[], categories=[], drivers=[], orders=[], tab='overview', period=7, timer, generation=0, role='owner', roleLabel='Dono';
const ROLE_TABS={kitchen:['kitchen','orders','settings'],cashier:['overview','orders','kitchen','customers','drivers','sales','settings'],manager:null,owner:null};
export async function renderDashboard(){
  const me=await api('/api/admin/store');store=me.store;role=me.role;roleLabel=me.role_label;document.title='Painel • '+store.name;
  $('#app').innerHTML='<div class="dashboard"><header class="dashboard-head">'+brand()+'<nav class="dashboard-nav">'+[['overview','Visão geral'],['orders','Pedidos'],['kitchen','Cozinha'],['products','Cardápio'],['stock','Estoque'],['customers','Clientes'],['drivers','Entregas'],['sales','Vendas e caixa'],['finance','Lucro e custos'],['integrations','Integrações']].filter(([id])=>role==='owner'||(role==='manager'?id!=='integrations':ROLE_TABS[role].includes(id))).map(([id,label])=>'<button data-tab="'+id+'">'+label+'</button>').join('')+'</nav>'+'<div class="head-actions"><button id="sound-toggle" class="icon-btn sound-toggle" aria-label="Som de novos pedidos">'+icon('bell')+'</button><button class="icon-btn" data-tab="settings" aria-label="Configurações">'+icon('gear')+'</button><button id="logout" class="icon-btn" aria-label="Sair">'+icon('logout')+'</button></div></header><main id="main" class="dashboard-main"><section class="dashboard-title"><div><span class="eyebrow" id="page-kicker">SEU COMÉRCIO EM MOVIMENTO</span><h1 id="page-title">Seu dia em um olhar</h1><p id="page-subtitle">Tudo pronto para vender mais.</p></div><div class="title-actions"><button id="store-toggle" class="badge gray"><i></i>Loja fechada</button><a class="btn" href="/loja/'+esc(store.slug)+'" target="_blank" rel="noopener">Ver minha loja '+icon('eye')+'</a></div></section><section id="platform-notices"></section><section id="dashboard-content" aria-live="polite"></section></main><footer class="dashboard-footer"><span>SeuComércioAqui</span><span>'+esc(store.name)+' • '+esc(auth.user.name)+' ('+esc(roleLabel)+')</span></footer></div>';
  $$('[data-tab]').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
  $('#logout').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'});location.href='/entrar';}catch(e){toast(e.message);}};
  $('#store-toggle').onclick=async()=>{try{const result=await api('/api/admin/store/open',{method:'POST',body:JSON.stringify({open:!store.open})});store=result.store;updateStoreButton();toast(store.open?'Loja aberta para pedidos.':'Loja fechada.');}catch(e){toast(e.message);}};
  updateStoreButton();updateSoundButton();
  document.addEventListener('pointerdown',unlockAudio,{once:true});
  $('#sound-toggle').onclick=()=>{try{localStorage.setItem('sca.sound',soundOn()?'0':'1');}catch{}unlockAudio();updateSoundButton();
    if(soundOn()){chime();if('Notification' in window&&Notification.permission==='default')Notification.requestPermission().catch(()=>{});}
    toast(soundOn()?'Som de novos pedidos ligado.':'Som de novos pedidos desligado.');};
  platformNotices();watchOrders();
  await switchTab(role==='kitchen'?'kitchen':'overview');
}
function updateStoreButton(){const b=$('#store-toggle');b.className='badge '+(store.open_now?'green':store.open?'amber':'gray');b.innerHTML='<i></i>'+(!store.open?'Loja fechada':store.open_now?'Loja aberta':'Aberta • fora do horário');b.title=store.open?'Clique para fechar a loja agora':'Clique para abrir a loja';}
const days=['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'];
let seen=null,watchTimer,audio;
const soundOn=()=>{try{return localStorage.getItem('sca.sound')!=='0';}catch{return true;}};
function unlockAudio(){try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();audio.resume();}catch{}}
function chime(){
  if(!soundOn()||!audio)return;
  [0,.18,.36].forEach((delay,i)=>{const o=audio.createOscillator(),g=audio.createGain();o.type='sine';o.frequency.value=[880,1175,1568][i];
    g.gain.setValueAtTime(.0001,audio.currentTime+delay);g.gain.exponentialRampToValueAtTime(.35,audio.currentTime+delay+.02);g.gain.exponentialRampToValueAtTime(.0001,audio.currentTime+delay+.35);
    o.connect(g).connect(audio.destination);o.start(audio.currentTime+delay);o.stop(audio.currentTime+delay+.4);});
}
function updateSoundButton(){const b=$('#sound-toggle');if(!b)return;b.classList.toggle('active',soundOn());b.setAttribute('aria-pressed',String(soundOn()));b.title=soundOn()?'Som de novos pedidos ligado':'Som de novos pedidos desligado';}
async function watchOrders(){
  clearTimeout(watchTimer);
  try{
    const list=(await api('/api/admin/orders?status=new')).orders;
    if(seen){const fresh=list.filter(o=>!seen.has(o.id));if(fresh.length){
      chime();if(autoPrint())fresh.slice().reverse().forEach(printTicket);const first=fresh[0];toast(fresh.length>1?fresh.length+' novos pedidos chegaram!':'Novo pedido #'+first.number+' • '+money(first.total));
      if('Notification' in window&&Notification.permission==='granted'&&document.hidden){try{new Notification('Novo pedido #'+first.number,{body:first.customer+' • '+money(first.total),icon:'/static/icon-192.png',tag:'pedido-'+first.id});}catch{}}
      if(['overview','orders','kitchen'].includes(tab))switchTab(tab,true);
    }}
    seen=new Set(list.map(o=>o.id));document.title=(list.length?'('+list.length+') ':'')+'Painel • '+store.name;
  }catch(e){if(e.status===401){location.href='/entrar';return;}}
  watchTimer=setTimeout(watchOrders,15000);
}
const autoPrint=()=>{try{return localStorage.getItem('sca.autoprint')==='1';}catch{return false;}};
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
function ticketHTML(o){
  const line=(a,b)=>'<div class="t-line"><span>'+a+'</span><span>'+b+'</span></div>';
  return '<div class="ticket"><h1>'+esc(store.name)+'</h1><p class="t-center">PEDIDO <b>#'+o.number+'</b><br>'+date(o.created_at)+(o.source==='counter'?' • balcão':'')+'</p>'+
    (o.scheduled_for?'<p class="t-box">AGENDADO: '+new Date(o.scheduled_for).toLocaleString('pt-BR',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+'</p>':'')+
    '<p><b>'+esc(o.customer)+'</b><br>'+esc(o.phone)+'</p><p class="t-box">'+(o.mode==='delivery'?'ENTREGA'+(o.zone?' • '+esc(o.zone):'')+'<br>'+esc(o.address):'RETIRADA NO BALCÃO')+'</p><hr>'+
    o.items.map(i=>'<div class="t-item"><b>'+i.quantity+'x '+esc(i.name)+'</b><span>'+money(i.unit_price*i.quantity)+'</span></div>'+i.extras.map(x=>'<div class="t-sub">+ '+esc(x.name)+'</div>').join('')+(i.notes?'<div class="t-sub">OBS: '+esc(i.notes)+'</div>':'')).join('')+
    (o.notes?'<hr><p><b>Observações:</b> '+esc(o.notes)+'</p>':'')+'<hr>'+line('Produtos',money(o.subtotal))+(o.delivery_fee?line('Entrega',money(o.delivery_fee)):'')+(o.discount?line('Desconto','- '+money(o.discount)):'')+'<div class="t-line t-total"><span>TOTAL</span><span>'+money(o.total)+'</span></div>'+
    line('Pagamento',pay[o.payment]+(o.paid?' (PAGO)':''))+(o.change_for?line('Troco para',money(o.change_for)):'')+'<p class="t-center t-foot">SeuComércioAqui</p></div>';
}
let printQueue=Promise.resolve();
function printTicket(o){
  printQueue=printQueue.then(()=>new Promise(resolve=>{
    let area=$('#print-area');if(!area){area=document.createElement('div');area.id='print-area';document.body.appendChild(area);}
    area.innerHTML=ticketHTML(o);document.body.classList.add('printing-ticket');
    const done=()=>{document.body.classList.remove('printing-ticket');area.innerHTML='';window.removeEventListener('afterprint',done);setTimeout(resolve,300);};
    window.addEventListener('afterprint',done);setTimeout(()=>window.print(),50);
  }));
}
function alertsPanel(){
  return '<section class="panel" id="alerts-panel"><div class="section-heading"><div><h2>Avisos e impressão neste aparelho</h2><p class="muted">Valem para este celular ou computador. Ative em cada aparelho que recebe pedidos.</p></div><span class="feature-icon">'+icon('bell')+'</span></div>'+
    '<div class="alert-row"><div><b>Aviso de pedido novo, mesmo com o painel fechado</b><p class="muted" id="push-status">Verificando…</p></div><div class="row-actions"><button type="button" class="btn" id="push-toggle">Ativar avisos</button><button type="button" class="btn secondary" id="push-test" hidden>Testar</button></div></div>'+
    '<div class="alert-row"><div><b>Imprimir automaticamente cada pedido novo</b><p class="muted">Com o painel aberto. Para imprimir sem a janela de confirmação, abra o Chrome com a opção <code>--kiosk-printing</code> e deixe a impressora térmica como padrão.</p></div><label class="switch"><input type="checkbox" id="autoprint" '+(autoPrint()?'checked':'')+'><span>'+(autoPrint()?'Ligado':'Desligado')+'</span></label></div></section>';
}
async function bindAlertsPanel(){
  const status=$('#push-status'),toggle=$('#push-toggle'),test=$('#push-test');if(!status)return;
  const labels={on:'Ativado neste aparelho.',off:'Desativado neste aparelho.',denied:'Bloqueado: libere as notificações deste site nas configurações do navegador.',unsupported:'Este navegador não aceita avisos. No iPhone, use “Adicionar à Tela de Início” e abra o painel por lá.'};
  const draw=async()=>{const s=await pushState().catch(()=>'off');status.textContent=labels[s];toggle.textContent=s==='on'?'Desativar avisos':'Ativar avisos';toggle.disabled=s==='unsupported'||s==='denied';test.hidden=s!=='on';toggle.dataset.state=s;};
  toggle.onclick=async()=>{toggle.disabled=true;try{if(toggle.dataset.state==='on'){await disablePush();toast('Avisos desativados neste aparelho.');}else{await enablePush();toast('Avisos ativados! Teste para conferir.');}}catch(e){toast(e.message);}await draw();};
  test.onclick=async()=>{try{const r=await api('/api/admin/push/test',{method:'POST'});toast(r.sent?'Aviso de teste enviado.':'Nenhum aparelho ativo encontrado.');}catch(e){toast(e.message);}};
  $('#autoprint').onchange=e=>{try{localStorage.setItem('sca.autoprint',e.target.checked?'1':'0');}catch{}e.target.nextElementSibling.textContent=e.target.checked?'Ligado':'Desligado';if(e.target.checked)toast('Pedidos novos serão impressos enquanto o painel estiver aberto.');};
  draw();
}
async function platformNotices(){
  try{const r=await api('/api/admin/notices');
    $('#platform-notices').innerHTML=(r.blocked_reason?'<div class="platform-notice alert"><b>Sua loja está bloqueada pela plataforma.</b><p>'+esc(r.blocked_reason)+' Fale com o suporte do SeuComércioAqui para regularizar.</p></div>':'')+
      r.notices.map(n=>'<div class="platform-notice '+esc(n.kind)+'"><b>'+esc(n.title)+'</b><p>'+esc(n.body)+'</p></div>').join('');
  }catch{}
}
async function switchTab(next,quiet=false){
  clearTimeout(timer);$('#new-manual-order')?.remove();tab=next;$('#dashboard-content').dataset.management=next;const v=++generation;
  const titles={kitchen:['Fila de produção','Produtos e observações para preparar os pedidos.'],finance:['Seu lucro, com clareza','Custos, taxas e resultado estimado da loja.'],stock:['Estoque sob controle','Reposição, perdas e histórico de movimentações.'],customers:['Conheça seus clientes','Compras e histórico de quem pede na sua loja.'],integrations:['Conecte seus parceiros','Chaves de API e acompanhamento das entregas.'],overview:['Seu dia em um olhar','Os pedidos e números que importam agora.'],orders:['Cada pedido, no seu tempo','Do primeiro clique à última entrega.'],products:['Seu cardápio, sua assinatura','Organize seus produtos e deixe tudo com a sua cara.'],drivers:['Entrega bem cuidada','Sua equipe e os pedidos a caminho.'],sales:['Os números do seu negócio','Acompanhe vendas, recebimentos e despesas.'],settings:['A sua loja, do seu jeito','Identidade, contato e operação em um só lugar.']};
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
    }else if(['finance','stock','customers','integrations'].includes(tab)){await managementView(tab,$('#dashboard-content'));}else settingsPage();
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
  $('#dashboard-content').innerHTML='<div class="metrics three">'+metric('Vendas concluídas hoje',money(today.revenue),'chart')+metric('Pedidos hoje',today.orders,'bag')+metric('Em andamento',active.length,'clock')+'</div><section class="panel order-panel"><div class="section-heading"><div><h2>Pedidos em andamento</h2><p class="muted">Um próximo passo para cada pedido.</p></div><button id="all-orders" class="text-link">Ver todos '+icon('arrow')+'</button></div>'+orderBoard(active)+'</section><div class="overview-bottom"><section class="panel"><div class="section-heading"><div><span class="muted">Vendas concluídas • últimos 7 dias</span><h2>'+money(week.revenue)+'</h2></div>'+icon('chart')+'</div>'+chart(week.chart)+'</section><section class="share-panel"><span class="feature-icon">'+icon('link')+'</span><h2>Seu cardápio está no ar.</h2><p>Compartilhe o link e receba pedidos diretamente pela sua loja.</p><button id="share-store" class="btn">'+icon('copy')+' Copiar link da loja</button></section></div>'+(!products.length&&!store.open?'<p class="muted">Primeiros passos: cadastre seus produtos, configure pagamentos e abra a loja quando estiver tudo pronto.</p>':'');
  $('#dashboard-content').insertAdjacentHTML('beforeend','<section id="overview-details"></section>');overviewDetails($('#overview-details')).catch(e=>toast(e.message));
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
function nextStatus(order){return {new:'preparing',preparing:'ready',ready:order.mode==='delivery'?'delivering':'completed',delivering:'completed'}[order.status];}
function actionLabel(order){return {new:'Aceitar pedido',preparing:'Marcar pronto',ready:order.mode==='delivery'?'Saiu para entrega':'Concluir retirada',delivering:'Concluir entrega'}[order.status];}
function orderCard(o){
  const minutes=Math.max(0,Math.round((Date.now()-new Date(o.created_at).getTime())/60000));
  return '<article class="order-card"><button class="order-detail" data-detail="'+o.id+'" aria-label="Ver pedido '+o.number+'"><div class="order-top"><b>#'+o.number+'</b><small>'+ (minutes<60?'há '+minutes+' min':date(o.created_at))+'</small></div><div class="order-customer"><span class="avatar">'+esc(o.customer.split(' ').slice(0,2).map(x=>x[0]).join('').toUpperCase())+'</span><div><b>'+esc(o.customer)+'</b><small>'+esc(o.items.map(x=>x.quantity+' × '+x.name).join(', '))+'</small></div></div><div class="order-meta"><span class="badge tiny">'+icon(o.mode==='delivery'?'truck':'bag')+(o.mode==='delivery'?'Entrega':'Retirada')+'</span>'+(o.scheduled_for?'<span class="badge tiny amber" title="Pedido agendado">'+icon('clock')+new Date(o.scheduled_for).toLocaleString('pt-BR',{weekday:'short',hour:'2-digit',minute:'2-digit'})+'</span>':'')+(o.rating?'<span class="badge tiny" title="Avaliação do cliente">'+'★'.repeat(o.rating)+'</span>':'')+'<strong>'+money(o.total)+'</strong></div></button>'+ (nextStatus(o)?'<button class="btn small full order-next '+(o.status==='preparing'?'lime':'')+'" data-next="'+o.id+'">'+actionLabel(o)+'</button>':'')+'</article>';
}
function bindOrderButtons(){
  if(!$('#new-manual-order')&&['orders','overview'].includes(tab)){$('.title-actions').insertAdjacentHTML('afterbegin','<button id="new-manual-order" class="btn secondary">'+icon('plus')+' Novo pedido</button>');$('#new-manual-order').onclick=()=>manualOrder(()=>switchTab('orders'));}
  bindLanes();
  $$('[data-detail]').forEach(b=>b.onclick=()=>orderDialog(orders.find(o=>o.id===Number(b.dataset.detail))));
  $$('[data-next]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const order=orders.find(o=>o.id===Number(b.dataset.next));await api('/api/admin/orders/'+order.id,{method:'PATCH',body:JSON.stringify({status:nextStatus(order)})});toast('Pedido atualizado.');await switchTab(tab,true);}catch(e){toast(e.message);b.disabled=false;}});
}
function ordersPage(){
  $('#dashboard-content').innerHTML='<div class="page-toolbar"><div class="chips"><button class="chip active" data-filter="active">Em andamento</button><button class="chip" data-filter="completed">Concluídos</button><button class="chip" data-filter="cancelled">Cancelados</button></div><label class="search compact">'+icon('search')+'<span class="sr-only">Buscar pedido</span><input id="order-search" placeholder="Número ou cliente"></label></div><div id="orders-area">'+orderBoard(orders.filter(o=>!['completed','cancelled'].includes(o.status)))+'</div><p class="muted">Em andamento: todos os pedidos ativos. Histórico: até 500 pedidos por status.</p>';
  let filter='active';
  async function show(){
    const term=$('#order-search').value.toLowerCase();
    const list=orders.filter(o=>(filter==='active'?!['completed','cancelled'].includes(o.status):o.status===filter)&&(!term||(o.customer+' '+o.number).toLowerCase().includes(term)));
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
  const d=modal('Pedido #'+o.number,'<div class="order-dialog-top"><div><h3>'+esc(o.customer)+'</h3><p>'+esc(o.phone)+' • '+date(o.created_at)+'</p><span class="badge">'+statuses[o.status]+'</span></div><div class="drawer-tools"><a class="btn secondary small" target="_blank" rel="noopener" href="https://wa.me/'+o.phone.replace(/\D/g,'').replace(/^(?!55)/,'55')+'?text='+encodeURIComponent('Olá, '+o.customer.split(' ')[0]+'! Sobre o seu pedido #'+o.number+':')+'">WhatsApp</a><button id="print-order" class="btn secondary small">'+icon('print')+' Imprimir</button></div></div>'+(nextStatus(o)?'<button id="drawer-next" class="btn full drawer-next">'+actionLabel(o)+' '+icon('arrow')+'</button>':'')+'<div class="notice">'+icon(o.mode==='delivery'?'truck':'store')+' '+(o.mode==='delivery'?'Entrega: '+esc(o.address)+(o.zone?' • Bairro '+esc(o.zone):''):'Retirada no balcão')+'</div>'+o.items.map(x=>'<div class="tracking-item"><div><b>'+x.quantity+' × '+esc(x.name)+'</b><small>'+x.extras.map(e=>esc(e.name)).join(', ')+'</small><small>'+esc(x.notes)+'</small></div><b>'+money(x.unit_price*x.quantity)+'</b></div>').join('')+
  (o.notes?'<p class="notice">Observações: '+esc(o.notes)+'</p>':'')+'<div class="checkout-totals"><div><span>Produtos</span><b>'+money(o.subtotal)+'</b></div><div><span>Entrega</span><b>'+money(o.delivery_fee)+'</b></div><div><span>Desconto</span><b>− '+money(o.discount)+'</b></div><div class="total-row"><span>Total</span><strong>'+money(o.total)+'</strong></div></div><p>'+pay[o.payment]+(o.change_for?' • Troco para '+money(o.change_for):'')+'</p><form id="order-update">'+
  '<label class="check-row"><span><input name="paid" type="checkbox" '+(o.paid?'checked':'')+' '+(o.status==='cancelled'?'disabled':'')+'>Pagamento confirmado</span></label>'+
  (o.mode==='delivery'?'<label>Entregador<select name="driver_id"><option value="">Sem entregador</option>'+drivers.filter(x=>x.active||x.id===o.driver_id).map(x=>'<option value="'+x.id+'" '+(x.id===o.driver_id?'selected':'')+'>'+esc(x.name)+'</option>').join('')+'</select></label>':'')+
  '<p class="form-error" role="alert" hidden></p><div class="dialog-actions"><button class="btn" type="submit">Salvar atualização</button><button class="btn secondary" id="copy-track" type="button">'+icon('link')+' Link do pedido</button></div></form>'+
  (!['completed','cancelled'].includes(o.status)?'<button id="cancel-order" class="text-danger">Cancelar pedido</button>':'')+'<details class="help"><summary>Histórico do pedido</summary>'+o.events.map(e=>'<p>'+statuses[e.status]+' • '+date(e.created_at)+'</p>').join('')+'</details>','drawer');
  if($('#drawer-next'))$('#drawer-next').onclick=async e=>{e.target.disabled=true;try{await api('/api/admin/orders/'+o.id,{method:'PATCH',body:JSON.stringify({status:nextStatus(o)})});closeModal();toast('Pedido atualizado.');switchTab(tab,true);}catch(err){toast(err.message);e.target.disabled=false;}};
  $('.dialog-actions',d).insertAdjacentHTML('beforeend','<button id="order-costs" type="button" class="btn secondary">Conferir custos</button>');$('#order-costs').onclick=()=>costsDialog(o,()=>switchTab(tab,true));
  $('#print-order').onclick=()=>printTicket(o);$('#copy-track').onclick=()=>copy(location.origin+'/pedido/'+o.tracking_token);
  bindForm($('#order-update'),async form=>{await api('/api/admin/orders/'+o.id,{method:'PATCH',body:JSON.stringify({paid:o.status==='cancelled'?!!o.paid:form.has('paid'),driver_id:form.get('driver_id')?Number(form.get('driver_id')):null})});closeModal();toast('Pedido atualizado.');switchTab(tab,true);});
  if($('#cancel-order'))$('#cancel-order').onclick=()=>{
    const confirm=modal('Cancelar este pedido?','<p>O pedido #'+o.number+' será cancelado. Os itens voltarão ao estoque. Se houve pagamento, combine a devolução diretamente com o cliente.</p><div class="dialog-actions"><button id="confirm-cancel" class="btn danger">Confirmar cancelamento</button><button id="keep-order" class="btn secondary">Manter pedido</button></div>');
    $('#keep-order').onclick=()=>orderDialog(o);
    $('#confirm-cancel').onclick=async()=>{try{await api('/api/admin/orders/'+o.id,{method:'PATCH',body:JSON.stringify({status:'cancelled'})});closeModal();toast('Pedido cancelado.');switchTab(tab,true);}catch(e){toast(e.message);}};
  };
}
function productsPage(){
  $('#dashboard-content').innerHTML='<div class="page-toolbar"><div class="chips"><button class="chip active" id="catalog-tab">Produtos</button><button class="chip" id="coupon-tab">Cupons</button></div><div class="toolbar-actions"><button id="categories-btn" class="btn secondary">'+icon('tag')+' Categorias</button><button id="new-product" class="btn">'+icon('plus')+' Novo produto</button></div></div><div class="metrics three">'+metric('Produtos cadastrados',products.length,'store')+metric('Disponíveis',products.filter(p=>p.active&&p.stock!==0).length,'check')+metric('Estoque baixo',products.filter(p=>p.active&&p.stock!==null&&p.stock<5).length,'bag')+'</div><section class="panel"><div class="section-heading"><h2>Produtos da loja</h2><label class="search compact">'+icon('search')+'<span class="sr-only">Buscar produto</span><input id="product-search" placeholder="Buscar produto"></label></div><div id="admin-products"></div></section>';
  $('#new-product').onclick=()=>productEditor();$('#categories-btn').onclick=categoriesDialog;$('#coupon-tab').onclick=couponsPage;$('#catalog-tab').onclick=productsPage;
  $('#product-search').oninput=renderProductTable;renderProductTable();
}
function renderProductTable(){
  const search=$('#product-search').value.toLowerCase();
  const list=products.filter(p=>(p.name+' '+p.description).toLowerCase().includes(search));
  $('#admin-products').innerHTML=list.length?'<div class="table-wrap"><table><thead><tr><th>Produto</th><th>Categoria</th><th>Preço</th><th>Estoque</th><th>Status</th><th><span class="sr-only">Ações</span></th></tr></thead><tbody>'+list.map(p=>'<tr><td><div class="table-product"><img src="'+esc(image(p.image))+'" alt=""><div><b>'+esc(p.name)+'</b><small>'+esc(p.description)+'</small></div></div></td><td>'+esc(categories.find(c=>c.id===p.category_id)?.name||'Outros')+'</td><td>'+money(p.price)+'</td><td>'+(p.stock===null?'Sem controle':p.stock+' un.')+'</td><td><span class="badge '+(p.active&&p.stock!==0?'green':'gray')+'">'+(p.active?(p.stock===0?'Esgotado':'Ativo'):'Pausado')+'</span></td><td><button class="icon-btn" data-edit-product="'+p.id+'" aria-label="Editar '+esc(p.name)+'">'+icon('edit')+'</button></td></tr>').join('')+'</tbody></table></div>':empty('Seu cardápio começa aqui','Adicione uma foto, um nome e um preço ao primeiro produto.','<button class="btn" id="empty-product">Adicionar produto</button>');
  $$('[data-edit-product]').forEach(b=>b.onclick=()=>productEditor(products.find(p=>p.id===Number(b.dataset.editProduct))));
  if($('#empty-product'))$('#empty-product').onclick=()=>productEditor();attachFallbacks($('#admin-products'));
}
function uploadField(name,label,value=''){
 return '<label>'+label+'<div class="upload-row"><input name="'+name+'" value="'+esc(value)+'" placeholder="URL HTTPS ou envie uma foto"><input type="file" accept="image/jpeg,image/png,image/webp" data-upload="'+name+'" aria-label="Enviar '+label+'"></div><small>Fotos de até 8 MB. A imagem é otimizada no servidor.</small></label>';
}
function bindUploads(root){
  $$('[data-upload]',root).forEach(input=>input.onchange=async()=>{
    const file=input.files[0];if(!file)return;if(file.size>8*1024*1024){toast('Use uma foto de até 8 MB.');input.value='';return;}
    input.disabled=true;const buttons=$$('button[type=submit]',root);buttons.forEach(b=>b.disabled=true);
    try{const form=new FormData();form.append('file',file);const result=await api('/api/admin/upload',{method:'POST',body:form});$('[name='+input.dataset.upload+']',root).value=result.url;toast('Foto enviada. Salve para aplicar.');}
    catch(e){toast(e.message);}finally{input.disabled=false;buttons.forEach(b=>b.disabled=false);}
  });
}
function productEditor(p=null){
  const d=modal(p?'Editar produto':'Novo produto','<form id="product-form"><div class="form-grid">'+field('name','Nome do produto',p?.name||'','text','required minlength="2" maxlength="120"')+moneyInput('price','Preço',p?.price||0)+'</div><label>Custo do produto (vazio = a informar)<div class="money-input"><span>R$</span><input name="unit_cost" aria-label="Custo do produto" type="number" min="0" step=".01" value="'+(p?.unit_cost==null?'':(p.unit_cost/100).toFixed(2))+'"></div></label>'+field('low_stock','Alertar estoque em (unidades)',p?.low_stock??5,'number','min="0" max="1000000" step="1" required')+'<label>Descrição<textarea name="description" maxlength="500" placeholder="Ingredientes e o que torna esse produto especial">'+esc(p?.description||'')+'</textarea></label><div class="form-grid"><label>Categoria<select name="category_id"><option value="">Outros</option>'+categories.map(c=>'<option value="'+c.id+'" '+(p?.category_id===c.id?'selected':'')+'>'+esc(c.name)+'</option>').join('')+'</select></label>'+field('stock','Estoque (vazio = sem controle)',p?.stock??'','number','min="0" step="1"')+'</div>'+uploadField('image','Foto do produto',p?.image||'')+'<div class="check-options"><label><input type="checkbox" name="active" '+(!p||p.active?'checked':'')+'> Disponível no cardápio</label><label><input type="checkbox" name="featured" '+(p?.featured?'checked':'')+'> Destaque da casa</label></div><fieldset class="groups-editor"><legend>Escolhas do cliente <small>Tamanho, sabores, molhos, ponto da carne…</small></legend><div id="group-rows"></div><div class="group-templates"><span class="muted">Adicionar:</span><button type="button" class="chip" data-template="size">Tamanho P/M/G</button><button type="button" class="chip" data-template="half">Meio a meio (2 sabores)</button><button type="button" class="chip" data-template="pick1">Escolha 1 (obrigatório)</button><button type="button" class="chip" data-template="blank">Grupo em branco</button></div></fieldset><fieldset><legend>Adicionais opcionais <small>Até 12 opções, cobradas à parte</small></legend><div id="extra-rows"></div><button type="button" id="add-extra" class="text-link">'+icon('plus')+' Adicionar complemento</button></fieldset>'+field('position','Ordem de exibição',p?.position||0,'number','min="0" step="1"')+'<p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Salvar produto</button></form>',true);
  const extras=structuredClone(p?.extras||[]);
  function drawExtras(){
    $('#extra-rows').innerHTML=extras.map((x,i)=>'<div class="extra-row"><input aria-label="Nome do complemento '+(i+1)+'" data-extra-name="'+i+'" placeholder="Ex.: queijo extra" value="'+esc(x.name)+'" maxlength="80" required><input aria-label="Preço do complemento '+(i+1)+'" data-extra-price="'+i+'" type="number" min="0" step=".01" value="'+(x.price/100).toFixed(2)+'" required><input aria-label="Custo do complemento '+(i+1)+'" data-extra-cost="'+i+'" type="number" min="0" step=".01" placeholder="Custo" value="'+(x.unit_cost==null?'':(x.unit_cost/100).toFixed(2))+'"><button type="button" class="icon-btn" data-remove-extra="'+i+'" aria-label="Remover complemento">'+icon('close')+'</button></div>').join('');
    $$('[data-extra-name]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraName)].name=x.value);
    $$('[data-extra-price]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraPrice)].price=cents(x.value));
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
    $('#group-rows').innerHTML=groups.map((g,i)=>'<div class="group-card"><div class="group-head"><input aria-label="Nome do grupo '+(i+1)+'" data-g-name="'+i+'" placeholder="Ex.: Tamanho" maxlength="60" value="'+esc(g.name)+'" required><button type="button" class="icon-btn" data-g-remove="'+i+'" aria-label="Remover grupo">'+icon('close')+'</button></div><div class="group-rules"><label>Mínimo<input type="number" min="0" max="30" data-g-min="'+i+'" value="'+g.min+'"></label><label>Máximo<input type="number" min="1" max="30" data-g-max="'+i+'" value="'+g.max+'"></label><label>Cobrança<select data-g-pricing="'+i+'"><option value="sum" '+(g.pricing==='sum'?'selected':'')+'>Soma as opções</option><option value="max" '+(g.pricing==='max'?'selected':'')+'>Cobra a mais cara (meio a meio)</option></select></label></div><p class="muted group-explain">'+(g.min?'Obrigatório: o cliente precisa escolher '+(g.min===g.max?g.min:'de '+g.min+' a '+g.max)+'.':'Opcional: até '+g.max+'.')+'</p>'+g.options.map((o,j)=>'<div class="extra-row"><input aria-label="Opção '+(j+1)+' do grupo '+(i+1)+'" data-o-name="'+i+'.'+j+'" placeholder="Nome da opção" maxlength="80" value="'+esc(o.name)+'" required><input aria-label="Preço da opção" data-o-price="'+i+'.'+j+'" type="number" min="0" step=".01" value="'+(o.price/100).toFixed(2)+'"><input aria-label="Custo da opção" data-o-cost="'+i+'.'+j+'" type="number" min="0" step=".01" placeholder="Custo" value="'+(o.unit_cost==null?'':(o.unit_cost/100).toFixed(2))+'"><button type="button" class="icon-btn" data-o-remove="'+i+'.'+j+'" aria-label="Remover opção">'+icon('close')+'</button></div>').join('')+'<button type="button" class="text-link" data-o-add="'+i+'">'+icon('plus')+' Adicionar opção</button></div>').join('')+(groups.some(g=>g.min)?'<p class="notice">Com escolha obrigatória, o preço do produto pode ser R$ 0,00: o cliente paga o valor das opções (ex.: tamanho). No cardápio aparece “a partir de”.</p>':'');
    const at=k=>k.split('.').map(Number);
    $$('[data-g-name]',d).forEach(x=>x.oninput=()=>groups[Number(x.dataset.gName)].name=x.value);
    $$('[data-g-min]',d).forEach(x=>x.onchange=()=>{groups[Number(x.dataset.gMin)].min=Math.max(0,Number(x.value)||0);drawGroups();});
    $$('[data-g-max]',d).forEach(x=>x.onchange=()=>{groups[Number(x.dataset.gMax)].max=Math.max(1,Number(x.value)||1);drawGroups();});
    $$('[data-g-pricing]',d).forEach(x=>x.onchange=()=>groups[Number(x.dataset.gPricing)].pricing=x.value);
    $$('[data-g-remove]',d).forEach(x=>x.onclick=()=>{groups.splice(Number(x.dataset.gRemove),1);drawGroups();});
    $$('[data-o-name]',d).forEach(x=>x.oninput=()=>{const [i,j]=at(x.dataset.oName);groups[i].options[j].name=x.value;});
    $$('[data-o-price]',d).forEach(x=>x.oninput=()=>{const [i,j]=at(x.dataset.oPrice);groups[i].options[j].price=cents(x.value||0);});
    $$('[data-o-cost]',d).forEach(x=>x.oninput=()=>{const [i,j]=at(x.dataset.oCost);groups[i].options[j].unit_cost=x.value===''?null:cents(x.value);});
    $$('[data-o-remove]',d).forEach(x=>x.onclick=()=>{const [i,j]=at(x.dataset.oRemove);if(groups[i].options.length===1)return toast('O grupo precisa de pelo menos uma opção.');groups[i].options.splice(j,1);drawGroups();});
    $$('[data-o-add]',d).forEach(x=>x.onclick=()=>{const g=groups[Number(x.dataset.oAdd)];if(g.options.length>=30)return toast('Use até 30 opções por grupo.');g.options.push(opt(''));drawGroups();});
  }
  $$('[data-template]',d).forEach(b=>b.onclick=()=>{if(groups.length>=10)return toast('Use até 10 grupos.');const first=!groups.some(g=>g.min);groups.push(templates[b.dataset.template]());drawGroups();if(first&&['size','half'].includes(b.dataset.template))$('[name=price]',d).value='0.00';});
  drawGroups();
  $('[name=price]',d).min='0';
  bindForm($('#product-form'),async form=>{
    const value={expected_stock:p?.stock??null,unit_cost:form.get('unit_cost')===''?null:cents(form.get('unit_cost')),low_stock:Number(form.get('low_stock')),name:form.get('name'),description:form.get('description'),price:cents(form.get('price')),category_id:form.get('category_id')?Number(form.get('category_id')):null,stock:form.get('stock')===''?null:Number(form.get('stock')),image:form.get('image'),active:form.has('active'),featured:form.has('featured'),position:Number(form.get('position')),extras,option_groups:groups.map(g=>({...g,min:Math.min(g.min,g.options.length),max:Math.min(Math.max(g.max,g.min,1),g.options.length)}))};
    await api('/api/admin/products'+(p?'/'+p.id:''),{method:p?'PUT':'POST',body:JSON.stringify(value)});
    closeModal();toast('Produto salvo.');await switchTab('products');
  });
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
  modal('Novo cupom','<form id="coupon-form">'+field('code','Código do cupom','','text','required minlength="3" maxlength="30" pattern="[A-Za-z0-9_-]+" placeholder="BEMVINDO10"')+'<div class="form-grid"><label>Tipo<select name="kind"><option value="percent">Percentual (%)</option><option value="fixed">Valor em reais (R$)</option></select></label>'+field('value','Desconto','','number','required min="0.01" step=".01"')+'</div>'+moneyInput('minimum','Pedido mínimo em produtos')+'<div class="form-grid">'+field('expires','Validade (opcional)','','date')+field('max_uses','Limite de usos (opcional)','','number','min="1" step="1"')+'</div><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Criar cupom</button></form>');
  bindForm($('#coupon-form'),async form=>{await api('/api/admin/coupons',{method:'POST',body:JSON.stringify({code:form.get('code').toUpperCase(),kind:form.get('kind'),value:form.get('kind')==='fixed'?cents(form.get('value')):Number(form.get('value')),minimum:cents(form.get('minimum')),expires:form.get('expires'),max_uses:form.get('max_uses')?Number(form.get('max_uses')):null})});closeModal();toast('Cupom criado.');couponsPage();});
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
  $('#dashboard-content').innerHTML='<form id="store-form"><section class="panel"><div class="section-heading"><div><h2>Identidade da loja</h2><p class="muted">A marca que seus clientes conhecem.</p></div><span class="feature-icon">'+icon('store')+'</span></div><div class="form-grid">'+field('name','Nome do comércio',store.name,'text','required minlength="2" maxlength="100"')+field('color','Cor principal',store.color,'color')+'</div><label>Descrição<textarea name="description" maxlength="500">'+esc(store.description)+'</textarea></label><div class="form-grid">'+uploadField('logo','Logo',store.logo)+uploadField('banner','Capa do cardápio',store.banner)+'</div><div class="notice">Seu link: <b>'+esc(location.origin+'/loja/'+store.slug)+'</b> <button class="text-link" type="button" id="settings-copy">'+icon('copy')+' Copiar</button></div></section><section class="panel"><h2>Contato e entrega</h2><div class="form-grid">'+field('phone','WhatsApp com DDD',store.phone,'tel','maxlength="20"')+field('delivery_minutes','Estimativa de entrega',store.delivery_minutes,'text','required maxlength="40"')+'</div><label>Endereço da loja<textarea name="address" maxlength="400">'+esc(store.address)+'</textarea></label><div class="form-grid">'+moneyInput('delivery_fee','Taxa de entrega',store.delivery_fee)+moneyInput('minimum_order','Pedido mínimo em produtos',store.minimum_order)+'</div></section><section class="panel"><div class="section-heading"><div><h2>Taxa por bairro</h2><p class="muted">Opcional. Com bairros cadastrados, o cliente escolhe o bairro e a taxa é calculada sozinha. Sem bairros, vale a taxa única acima.</p></div><span class="feature-icon">'+icon('truck')+'</span></div><div id="zone-rows" class="zone-rows">'+store.delivery_zones.map(zoneRow).join('')+'</div><button id="add-zone" class="btn secondary small" type="button">'+icon('plus')+' Adicionar bairro</button></section><section class="panel"><div class="section-heading"><div><h2>Horário de funcionamento</h2><p class="muted">A loja abre e fecha sozinha nesses horários. O botão Loja aberta/fechada continua valendo para fechar na hora que precisar.</p></div><span class="feature-icon">'+icon('clock')+'</span></div><label class="check-row"><span><input name="auto_hours" type="checkbox" '+(store.auto_hours?'checked':'')+'> Abrir e fechar automaticamente nestes horários</span></label><label class="check-row"><span><input name="allow_scheduling" type="checkbox" '+(store.allow_scheduling?'checked':'')+'> Aceitar pedidos agendados (até 7 dias, só dentro do horário)</span></label><div class="hours-editor">'+days.map((name,i)=>{const shifts=store.hours[String(i)]||[];const a=shifts[0]||['18:00','23:00'],b=shifts[1]||['',''];return '<div class="hours-row"><label class="check-row"><span><input type="checkbox" data-day="'+i+'" '+(shifts.length?'checked':'')+'> '+name+'</span></label><div class="hours-shifts"><input type="time" aria-label="'+name+': abre" data-start="'+i+'" value="'+a[0]+'"><span>às</span><input type="time" aria-label="'+name+': fecha" data-end="'+i+'" value="'+a[1]+'"><span class="muted">e</span><input type="time" aria-label="'+name+': abre no 2º turno" data-start2="'+i+'" value="'+b[0]+'"><span>às</span><input type="time" aria-label="'+name+': fecha no 2º turno" data-end2="'+i+'" value="'+b[1]+'"></div></div>';}).join('')+'</div><p class="muted">O 2º turno é opcional (ex.: almoço e jantar). Para virar a madrugada, use por exemplo 18:00 às 02:00.</p></section><section class="panel qr-panel"><div><h2>QR Code do cardápio</h2><p class="muted">Imprima e coloque no balcão, nas mesas, na sacola de entrega e no panfleto. O cliente aponta a câmera e cai direto no seu cardápio.</p><div class="qr-actions"><a class="btn" href="/api/admin/qrcode?format=png&amp;download=1">'+icon('print')+' Baixar para imprimir</a><a class="btn secondary" href="/api/admin/qrcode?download=1">Baixar em SVG</a></div></div><img src="/api/admin/qrcode" alt="QR Code que abre o cardápio da loja" width="180" height="180"></section><section class="panel"><h2>Pagamentos</h2><p class="muted">Pix é confirmado pela loja. Cartão é cobrado na entrega ou retirada.</p><div class="check-options">'+Object.entries(pay).map(([value,label])=>'<label><input name="payments" type="checkbox" value="'+value+'" '+(store.payments.includes(value)?'checked':'')+'> '+label+'</label>').join('')+'</div>'+field('pix_key','Chave Pix',store.pix_key,'text','maxlength="200"')+'</section><p class="form-error" role="alert" hidden></p><div class="settings-save"><button class="btn" type="submit">Salvar configurações '+icon('check')+'</button><button id="change-password" class="btn secondary" type="button">Alterar senha</button></div></form>';
  bindUploads($('#store-form'));$('#settings-copy').onclick=()=>copy(location.origin+'/loja/'+store.slug);$('#change-password').onclick=passwordDialog;
  $('#dashboard-content').insertAdjacentHTML('afterbegin',alertsPanel());bindAlertsPanel();
  if(role==='owner'){$('#dashboard-content').insertAdjacentHTML('afterbegin','<section class="panel" id="team-panel"><div class="loading small-loading">Carregando equipe…</div></section>');teamPanel();}
  const bindZones=()=>$$('[data-remove-zone]').forEach(b=>b.onclick=()=>b.closest('.zone-row').remove());bindZones();
  $('#add-zone').onclick=()=>{$('#zone-rows').insertAdjacentHTML('beforeend',zoneRow({name:'',fee:store.delivery_fee}));bindZones();$('#zone-rows .zone-row:last-child input').focus();};
  bindForm($('#store-form'),async form=>{
    const value={...store,name:form.get('name'),description:form.get('description'),phone:form.get('phone'),address:form.get('address'),delivery_minutes:form.get('delivery_minutes'),color:form.get('color'),logo:form.get('logo'),banner:form.get('banner'),delivery_fee:cents(form.get('delivery_fee')),minimum_order:cents(form.get('minimum_order')),payments:form.getAll('payments'),pix_key:form.get('pix_key'),auto_hours:form.has('auto_hours'),allow_scheduling:form.has('allow_scheduling'),hours:collectHours(),delivery_zones:$$('#zone-rows .zone-row').map(r=>({name:$('[data-zone-name]',r).value.trim(),fee:cents($('[data-zone-fee]',r).value||0)})).filter(z=>z.name)};
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

function kitchenPage(){
 const list=orders.filter(o=>['new','preparing','ready'].includes(o.status));
 $('#dashboard-content').innerHTML='<div class="page-toolbar"><span class="badge green">'+list.length+' pedidos na produção</span><button id="kitchen-refresh" class="btn secondary">Atualizar fila</button></div><div class="kitchen-grid">'+list.map(o=>'<article class="panel kitchen-ticket"><div class="section-heading"><h2>#'+o.number+'</h2><span class="badge">'+statuses[o.status]+'</span></div><small>'+date(o.created_at)+' • '+(o.mode==='delivery'?'Entrega':'Retirada')+'</small>'+o.items.map(i=>'<div class="kitchen-item"><b>'+i.quantity+' × '+esc(i.name)+'</b><p>'+i.extras.map(x=>esc(x.name)).join(', ')+'</p>'+(i.notes?'<p class="notice">'+esc(i.notes)+'</p>':'')+'</div>').join('')+(o.notes?'<p class="notice">'+esc(o.notes)+'</p>':'')+(o.status==='ready'?'<span class="badge green">Aguardando expedição</span>':'<button class="btn full" data-next="'+o.id+'">'+actionLabel(o)+'</button>')+'</article>').join('')+'</div>'+(!list.length?empty('Cozinha em dia','Novos pedidos e itens em preparo aparecem aqui.'):'');
 $('#kitchen-refresh').onclick=()=>switchTab('kitchen');bindOrderButtons();
}
