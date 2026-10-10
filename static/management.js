import { $, $$, api, auth, brand, icon, esc, money, date, modal, closeModal, bindForm, field, moneyInput, cents, toast, empty, copy, statuses } from './ui.js';

const amount = value => value === null || value === undefined ? 'A informar' : money(value);
const metric = (label,value,note='') => '<article class="metric"><div><small>'+esc(label)+'</small><strong>'+value+'</strong><span class="metric-note">'+esc(note)+'</span></div></article>';
const nullableMoney = (name,label,value) => '<label>'+esc(label)+'<div class="money-input"><span>R$</span><input name="'+esc(name)+'" aria-label="'+esc(label)+'" type="number" min="0" step=".01" value="'+(value==null?'':(value/100).toFixed(2))+'" placeholder="A informar"></div></label>';
let period=30;
function periods(){
  return '<div class="chips">'+[[1,'Hoje'],[7,'7 dias'],[30,'30 dias'],[90,'90 dias'],[365,'1 ano']].map(([n,l])=>'<button class="chip '+(period===n?'active':'')+'" data-days="'+n+'">'+l+'</button>').join('')+'</div>';
}
function bindPeriods(run){$$('[data-days]').forEach(b=>b.onclick=()=>{period=Number(b.dataset.days);run();});}
function table(headers,rows){return '<p class="table-hint">Arraste para o lado para ver todas as colunas.</p><div class="table-wrap" tabindex="0" aria-label="Tabela com rolagem horizontal"><table><thead><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>';}
function row(values){return '<tr>'+values.map(v=>'<td>'+v+'</td>').join('')+'</tr>';}
const auditLabel = action => ({'order.costs':'Custos de pedido atualizados','store.plan':'Contrato de loja atualizado','ledger.receipt':'Recebimento registrado','ledger.expense':'Despesa registrada','ledger.void':'Lançamento anulado','key.create':'Chave de integração criada','key.revoke':'Chave de integração revogada','store.block':'Loja bloqueada','store.unblock':'Loja desbloqueada','notice.create':'Aviso publicado para os lojistas','notice.toggle':'Aviso ativado ou desativado'}[action] || 'Alteração administrativa');

export async function managementView(tab,root){
  if(tab==='finance')await financePage(root);
  if(tab==='customers')await customersPage(root);
  if(tab==='stock')await stockPage(root);
  if(tab==='integrations')await integrationsPage(root);
}

async function financePage(root){
  const f=await api('/api/admin/finance?days='+period);
  if(!root.isConnected||root.dataset.management!=='finance')return;
  root.innerHTML='<div class="page-toolbar">'+periods()+'<button class="btn secondary" id="fee-settings">'+icon('gear')+' Custos e taxas</button></div>'+
    '<div class="metrics four">'+metric('Vendas concluídas',money(f.revenue))+metric('Lucro estimado',amount(f.estimated_profit),f.margin===null?'Complete os custos para calcular':'Margem de '+f.margin+'%')+metric('Custos de produtos',money(f.cogs),'Valores informados nos pedidos')+metric('Custos preenchidos',f.cost_coverage+'%',f.missing_cost_orders+' pedidos com pendências')+'</div>'+
    (f.missing_cost_orders?'<div class="notice warning"><b>O lucro depende dos custos.</b><p>'+f.missing_cost_orders+' pedidos concluídos têm custos pendentes. Preencha abaixo para calcular o resultado do período.</p></div>':'')+
    '<div class="sales-grid"><section class="panel"><h2>Resultado da operação</h2>'+[
      ['Vendas concluídas',f.revenue],['− Produtos / CMV',f.cogs],['− Entregas',f.delivery_cost],['− Taxas de pagamento',f.payment_fees],['− Comissão da plataforma',f.platform_fees],['− Despesas registradas',f.expenses]].map(([label,n])=>'<div class="payment-line"><span>'+label+'</span><b>'+money(n)+'</b></div>').join('')+'<div class="payment-line result-line"><b>Lucro estimado</b><strong>'+amount(f.estimated_profit)+'</strong></div><p class="muted">Pedidos concluídos pela data de criação. Estimativa com os custos informados, sem apuração contábil ou tributária automática. Registre mensalidades, impostos e outros gastos em Vendas → Nova despesa.</p></section>'+
    '<section class="panel"><h2>Contrato e custos da loja</h2><div class="payment-line"><span>Comissão sobre produtos após desconto</span><b>'+(f.commission_bps/100).toLocaleString('pt-BR')+'%</b></div><div class="payment-line"><span>Mensalidade configurada</span><b>'+money(f.monthly_fee)+'</b></div><div class="payment-line"><span>Custo padrão de entrega</span><b>'+amount(f.default_delivery_cost)+'</b></div><p class="muted">Novos custos e taxas valem para os próximos pedidos. O histórico mantém os valores da venda.</p><a class="btn secondary" href="/api/admin/export">Exportar pedidos</a></section></div>'+
    '<section class="panel"><div class="section-heading"><h2>Conferência dos pedidos</h2><span class="muted">Até 500 pedidos do período</span></div>'+table(['Pedido','Cliente','Total','Produtos','Entrega','Pagamento','Situação',''],f.orders.map(o=>row(['#'+o.number,esc(o.customer),money(o.total),o.missing_items?'A informar':amount(o.cogs),amount(o.delivery_cost),amount(o.payment_fee),esc(statuses[o.status]),'<button class="btn secondary small" data-cost="'+o.id+'">Conferir custos</button>'])))+(!f.orders.length?empty('Nenhum pedido no período','Os custos aparecem aqui conforme você recebe pedidos.'):'')+'</section>';
  bindPeriods(()=>financePage(root));$('#fee-settings').onclick=()=>feesDialog(f,()=>financePage(root));
  $$('[data-cost]').forEach(b=>b.onclick=async()=>{try{const result=await api('/api/admin/orders?status='+f.orders.find(o=>o.id===Number(b.dataset.cost)).status);const order=result.orders.find(o=>o.id===Number(b.dataset.cost));if(!order)throw Error('Pedido não encontrado.');costsDialog(order,()=>financePage(root));}catch(e){toast(e.message);}});
}
function feesDialog(f,done){
  modal('Custos dos próximos pedidos','<form id="fees-form"><p class="muted">Taxas percentuais em %. Ex.: 2,5 para uma taxa de 2,5%. Custo de entrega vazio mantém a pendência para conferência.</p>'+nullableMoney('delivery','Custo padrão de entrega',f.default_delivery_cost)+'<div class="form-grid">'+[['pix','Pix'],['cash','Dinheiro'],['card','Cartão']].map(([key,label])=>field(key,'Taxa de '+label+' (%)',(f.fees[key]||0)/100,'number','min="0" max="100" step=".01" required')).join('')+'</div><p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Salvar custos</button></form>');
  bindForm($('#fees-form'),async form=>{await api('/api/admin/finance/settings',{method:'PUT',body:JSON.stringify({payment_fees:Object.fromEntries(['pix','cash','card'].map(k=>[k,cents(form.get(k))])),default_delivery_cost:form.get('delivery')===''?null:cents(form.get('delivery'))})});closeModal();toast('Custos salvos para novos pedidos.');done();});
}
export function costsDialog(o,done){
  modal('Custos do pedido #'+o.number,'<form id="costs-form"><p class="muted">Informe o custo por unidade, incluindo os complementos escolhidos. Vazio significa custo pendente; zero significa sem custo.</p>'+o.items.map(i=>nullableMoney('item_'+i.id,i.quantity+' × '+i.name+' — custo por unidade',i.unit_cost)).join('')+(o.mode==='delivery'?nullableMoney('delivery_cost','Custo da entrega',o.delivery_cost):'')+nullableMoney('payment_fee','Taxa do pagamento (valor em R$)',o.payment_fee)+'<p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Salvar conferência</button></form>',true);
  bindForm($('#costs-form'),async form=>{const optional=k=>form.get(k)===''?null:cents(form.get(k));await api('/api/admin/orders/'+o.id+'/costs',{method:'PATCH',body:JSON.stringify({delivery_cost:o.mode==='delivery'?optional('delivery_cost'):0,payment_fee:optional('payment_fee'),items:o.items.map(i=>({id:i.id,unit_cost:optional('item_'+i.id)}))})});closeModal();toast('Custos atualizados.');done();});
}

async function customersPage(root){
  const {customers}=await api('/api/admin/customers');
  if(!root.isConnected||root.dataset.management!=='customers')return;
  root.innerHTML='<div class="metrics three">'+metric('Clientes',customers.length)+metric('Compraram novamente',customers.filter(c=>c.orders>1).length)+metric('Vendas concluídas',money(customers.reduce((a,c)=>a+c.spent,0)))+'</div><section class="panel"><div class="section-heading"><h2>Relacionamento com clientes</h2><label class="search compact">'+icon('search')+'<input id="customer-search" aria-label="Buscar cliente" placeholder="Nome ou telefone"></label></div><div id="customer-list"></div></section>';
  function draw(){const term=$('#customer-search').value.toLowerCase();const list=customers.filter(c=>(c.name+' '+c.phone).toLowerCase().includes(term));$('#customer-list').innerHTML=table(['Cliente','Telefone','Pedidos','Total comprado','Último pedido',''],list.map(c=>row([esc(c.name),esc(c.phone),c.orders,money(c.spent),date(c.last_order),'<button class="btn secondary small" data-customer="'+esc(c.phone)+'">Ver histórico</button>'])));$$('[data-customer]').forEach(b=>b.onclick=async()=>{try{const {orders}=await api('/api/admin/customers/'+encodeURIComponent(b.dataset.customer)+'/orders');modal('Histórico do cliente',table(['Pedido','Data','Situação','Valor'],orders.map(o=>row(['#'+o.number,date(o.created_at),esc(statuses[o.status]),money(o.total)])))+'<p class="muted">Até 100 pedidos recentes. Dados disponíveis apenas para sua loja.</p>',true);}catch(e){toast(e.message);}});}
  $('#customer-search').oninput=draw;draw();
}

async function stockPage(root){
  const s=await api('/api/admin/stock');
  if(!root.isConnected||root.dataset.management!=='stock')return;const controlled=s.products.filter(p=>p.stock!==null);
  root.innerHTML='<div class="metrics three">'+metric('Produtos com controle',controlled.length)+metric('Precisam de reposição',controlled.filter(p=>p.stock<=p.low_stock).length)+metric('Valor a custo conhecido',money(controlled.reduce((a,p)=>a+(p.unit_cost||0)*p.stock,0)),'Produtos sem custo ficam fora do valor')+'</div><section class="panel"><h2>Estoque e reposição</h2>'+table(['Produto','Disponível','Alerta em','Situação',''],s.products.map(p=>row([esc(p.name),p.stock===null?'Sem controle':p.stock+' un.',p.low_stock+' un.',p.stock!==null&&p.stock<=p.low_stock?'<span class="badge gray">Repor estoque</span>':'Em dia',p.stock===null?'Ative no Cardápio':'<button class="btn secondary small" data-adjust="'+p.id+'">Movimentar</button>'])))+'</section><section class="panel"><h2>Últimas movimentações</h2>'+table(['Produto','Movimento','Saldo','Motivo','Data'],s.movements.map(m=>row([esc(m.name),(m.delta>0?'+':'')+m.delta,m.balance,esc(m.reason),date(m.created_at)])))+'</section>';
  $$('[data-adjust]').forEach(b=>b.onclick=()=>{const p=s.products.find(p=>p.id===Number(b.dataset.adjust));modal('Movimentar '+p.name,'<form id="stock-form"><p>Estoque atual: <b>'+p.stock+' unidades</b></p>'+field('delta','Quantidade (negativa para saída)','','number','required min="-1000000" max="1000000" step="1"')+field('reason','Motivo','','text','required minlength="3" maxlength="200" placeholder="Compra, perda, inventário…"')+'<p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Registrar movimentação</button></form>');bindForm($('#stock-form'),async form=>{await api('/api/admin/stock/'+p.id+'/adjust',{method:'POST',body:JSON.stringify({delta:Number(form.get('delta')),reason:form.get('reason')})});closeModal();toast('Estoque atualizado.');stockPage(root);});});
}

async function integrationsPage(root){
  const result=await api('/api/admin/integrations');
  if(!root.isConnected||root.dataset.management!=='integrations')return;
  root.innerHTML='<div class="integration-hero panel"><span class="feature-icon">'+icon('link')+'</span><div><h2>Sua loja conectada</h2><p>API para parceiros consultarem entregas prontas e atualizarem a saída e a conclusão.</p></div><button id="new-api-key" class="btn">'+icon('plus')+' Criar chave de API</button></div><div class="sales-grid"><section class="panel"><h2>Conectar ao MotoJá</h2><p>Crie uma chave com leitura de pedidos e atualização de entregas. O parceiro poderá buscar pedidos prontos, vinculá-los uma única vez e informar os próximos status.</p><div class="notice warning"><b>API disponível. Conector do MotoJá pendente.</b><p>A conexão automática depende da configuração desse conector no MotoJá. Nenhum motoboy é acionado ao gerar uma chave.</p></div><a class="btn secondary" href="https://nexusmotoja.com.br/empresa.html" target="_blank" rel="noopener">Abrir MotoJá '+icon('arrow')+'</a></section><section class="panel"><h2>Dados da integração</h2><label>Endereço da API<input id="api-base" readonly value="'+esc(result.base_url+'/api/v1')+'"></label><button class="text-link" id="copy-api-base">'+icon('copy')+' Copiar endereço</button><p class="muted">Valores em centavos de real. Autenticação pelo cabeçalho Authorization: Bearer. Limite de 120 requisições por minuto por chave.</p><a class="btn secondary" href="/static/api-docs.html" target="_blank" rel="noopener">Documentação e exemplos</a></section></div><section class="panel"><h2>Chaves da loja</h2>'+table(['Nome','Identificação','Permissões','Último uso','Situação',''],result.keys.map(k=>row([esc(k.name),'<code>'+esc(k.prefix)+'…</code>',JSON.parse(k.scopes).map(esc).join('<br>'),k.last_used_at?date(k.last_used_at):'Ainda não usada',k.revoked_at?'Revogada':'Ativa',k.revoked_at?'':'<button class="btn secondary small" data-revoke="'+k.id+'">Revogar</button>'])))+(!result.keys.length?empty('Nenhuma chave criada','Você controla o acesso dos parceiros por loja.'):'')+'</section><section class="panel"><h2>Entregas vinculadas</h2>'+table(['Pedido','Parceiro','Código externo','Situação','Atualização'],result.deliveries.map(d=>row(['#'+d.number,esc(d.provider),esc(d.external_id),esc(d.status==='claimed'?'Vinculada':statuses[d.status]),date(d.updated_at)])))+'</section>';
  $('#copy-api-base').onclick=()=>copy(result.base_url+'/api/v1');
  $('#new-api-key').onclick=()=>{modal('Nova chave de integração','<form id="key-form">'+field('name','Nome da integração','MotoJá','text','required minlength="2" maxlength="80"')+'<fieldset><legend>Permissões</legend><label class="check-row"><span><input type="checkbox" name="scope" value="orders:read" checked> Consultar entregas prontas</span></label><label class="check-row"><span><input type="checkbox" name="scope" value="deliveries:write" checked> Vincular e atualizar entregas</span></label></fieldset><p class="muted">O parceiro terá dados de entrega da sua loja. Não terá acesso ao financeiro, ao pagamento ou a outras lojas.</p><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Gerar chave</button></form>');bindForm($('#key-form'),async form=>{const key=await api('/api/admin/integrations/keys',{method:'POST',body:JSON.stringify({name:form.get('name'),scopes:form.getAll('scope')})});modal('Guarde sua chave agora','<div class="notice warning">Esta é a única exibição da chave completa. Guarde-a no servidor do parceiro e não a publique.</div><label>Chave da integração<input id="generated-key" readonly value="'+esc(key.token)+'"></label><button class="btn full" id="copy-new-key">'+icon('copy')+' Copiar chave</button>');$('#copy-new-key').onclick=()=>copy(key.token);integrationsPage(root);});};
  $$('[data-revoke]').forEach(b=>b.onclick=()=>{modal('Revogar esta chave?','<p>A integração que usa essa chave perderá acesso imediatamente. Você poderá gerar outra.</p><button id="confirm-revoke" class="btn danger full">Revogar chave</button>');$('#confirm-revoke').onclick=async()=>{try{await api('/api/admin/integrations/keys/'+b.dataset.revoke,{method:'DELETE'});closeModal();toast('Chave revogada.');integrationsPage(root);}catch(e){toast(e.message);}};});
}

export async function manualOrder(done){
  const {products}=await api('/api/admin/products');const {store}=await api('/api/admin/store');
  const active=products.filter(p=>p.active&&p.stock!==0);
  if(!active.length)return toast('Cadastre um produto disponível primeiro.');
  const key=crypto.randomUUID();
  modal('Novo pedido de balcão','<form id="manual-order"><p class="muted">Para pedidos por telefone ou no balcão. Preços e estoque são conferidos no servidor. O pagamento é confirmado depois no pedido.</p><div class="form-grid">'+field('customer','Cliente','','text','required minlength="2" maxlength="100"')+field('phone','Telefone com DDD','','tel','required minlength="10" maxlength="20"')+'</div><div class="form-grid"><label>Atendimento<select name="mode"><option value="pickup">Retirada</option><option value="delivery">Entrega</option></select></label><label>Pagamento<select name="payment">'+store.payments.map(m=>'<option value="'+m+'">'+esc({pix:'Pix',cash:'Dinheiro',card:'Cartão'}[m])+'</option>').join('')+'</select></label></div>'+field('address','Endereço (para entrega)','','text','maxlength="400"')+'<fieldset><legend>Produtos e quantidades</legend>'+active.map(p=>'<div class="pos-item"><label>'+esc(p.name)+' <small>'+money(p.price)+'</small></label><input name="p_'+p.id+'" aria-label="Quantidade de '+esc(p.name)+'" type="number" min="0" max="50" step="1" value="0"></div>').join('')+'</fieldset><p class="muted">Para produtos com complementos, utilize o cardápio público para personalizar.</p>'+field('notes','Observações','','text','maxlength="500"')+'<p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Criar pedido</button></form>',true);
  bindForm($('#manual-order'),async form=>{const items=active.filter(p=>Number(form.get('p_'+p.id))>0).map(p=>({product_id:p.id,quantity:Number(form.get('p_'+p.id)),option_ids:[]}));const r=await api('/api/admin/orders',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({customer:form.get('customer'),phone:form.get('phone'),mode:form.get('mode'),payment:form.get('payment'),address:form.get('address'),notes:form.get('notes'),items})});closeModal();toast('Pedido #'+r.number+' criado.');done();});
}

export async function overviewDetails(root){
  const s=await api('/api/admin/insights?days=7');
  if(!root.isConnected)return;
  const r=s.readiness;
  root.innerHTML='<div class="metrics three">'+metric('Lucro estimado • 7 dias',amount(s.finance.estimated_profit),s.finance.missing_cost_orders+' pedidos com custos pendentes')+metric('Ticket médio • 7 dias',money(s.finance.completed?s.finance.revenue/s.finance.completed:0))+metric('Produtos com foto',r.photos+' / '+r.products,'Seu cardápio mais completo')+'</div><div class="sales-grid"><section class="panel"><h2>Mais vendidos • 7 dias</h2>'+table(['Produto','Unidades','Valor de produtos'],s.top_products.map(p=>row([esc(p.name),p.quantity,money(p.total)])))+(!s.top_products.length?'<p class="muted">Os produtos aparecem após concluir as primeiras vendas.</p>':'')+'</section><section class="panel"><h2>Atenção ao estoque</h2>'+s.low_stock.map(p=>'<div class="payment-line"><span>'+esc(p.name)+'</span><b>'+p.stock+' un.</b></div>').join('')+(!s.low_stock.length?'<p class="muted">Nenhum produto com estoque baixo.</p>':'')+'<h3 class="onboarding-title">Preparação da loja</h3><ul class="readiness">'+[[r.products>0,'Produtos cadastrados'],[r.address,'Endereço de retirada'],[r.phone,'Telefone da loja'],[r.products>0&&r.costs===r.products,'Custos dos produtos preenchidos'],[r.open,'Loja aberta para pedidos']].map(([ok,l])=>'<li>'+icon(ok?'check':'clock')+esc(l)+'</li>').join('')+'</ul></section></div>';
}

const monthName = label => { const [y,m] = label.split('-').map(Number); return new Date(y,m-1,15).toLocaleDateString('pt-BR',{month:'short',year:'2-digit'}).replace('.',''); };
const monthLong = label => { const [y,m] = label.split('-').map(Number); const t = new Date(y,m-1,15).toLocaleDateString('pt-BR',{month:'long',year:'numeric'}); return t[0].toUpperCase()+t.slice(1); };
const daysSince = value => value ? Math.floor((Date.now()-new Date(value).getTime())/86400000) : null;
const change = (now,before) => { if(!before)return now?'<span class="trend up">novo</span>':''; const pct=Math.round((now-before)/before*100); return '<span class="trend '+(pct>=0?'up':'down')+'">'+(pct>=0?'▲ ':'▼ ')+Math.abs(pct)+'% vs mês anterior</span>'; };
const series = {gmv:['Vendas das lojas',money],received:['Recebido pela plataforma',money],result:['Resultado da plataforma',money],orders:['Pedidos concluídos',v=>String(v)]};
let platformTab='monthly', chartSeries='gmv', selectedMonth='', storeFilter='all';

export async function renderPlatform(){
  if(!auth.user?.platform_admin){$('#app').innerHTML='<main id="main" class="loading">'+brand()+'<h1>Acesso restrito</h1><p>Esta área é exclusiva do dono da plataforma.</p><a class="btn" href="/painel">Voltar à loja</a></main>';return;}
  document.title='Dono da plataforma • SeuComércioAqui';
  const tabs=[['monthly','Visão mês a mês'],['stores','Lojas e contas'],['promos','Promoções e avisos'],['cash','Recebimentos e despesas'],['history','Histórico']];
  $('#app').innerHTML='<div class="dashboard platform"><header class="dashboard-head">'+brand()+'<nav class="dashboard-nav">'+tabs.map(([id,label])=>'<button data-ptab="'+id+'">'+label+'</button>').join('')+'</nav><a class="platform-entry btn secondary" href="/painel">'+icon('store')+' Minha loja</a><div class="head-actions"><span class="muted">Plataforma</span><button class="icon-btn" id="platform-logout" aria-label="Sair">'+icon('logout')+'</button></div></header><main class="dashboard-main" id="main"><section class="dashboard-title"><div><span class="eyebrow">GESTÃO DA PLATAFORMA</span><h1 id="platform-title">Seu negócio por inteiro</h1><p id="platform-subtitle">Lojas, contratos e resultados do SeuComércioAqui.</p></div><span class="badge green">Acesso do proprietário</span></section><section id="platform-content"></section></main></div>';
  $('#platform-logout').onclick=async()=>{await api('/api/auth/logout',{method:'POST'});location.href='/entrar';};
  $$('[data-ptab]').forEach(b=>b.onclick=()=>{platformTab=b.dataset.ptab;draw();});
  const root=$('#platform-content');
  const titles={monthly:['Suas vendas mês a mês','Quanto as lojas venderam e quanto a plataforma recebeu em cada mês.'],stores:['Lojas e contas','Contratos, pagamentos do mês, bloqueios e saúde de cada loja.'],promos:['Promoções e avisos','Mensalidades promocionais e recados que aparecem no painel de todos os lojistas.'],cash:['Recebimentos e despesas','O dinheiro que entrou e saiu da plataforma.'],history:['Histórico administrativo','Tudo o que foi alterado, com data.']};
  async function draw(){
    $$('[data-ptab]').forEach(b=>b.classList.toggle('active',b.dataset.ptab===platformTab));
    $('#platform-title').textContent=titles[platformTab][0];$('#platform-subtitle').textContent=titles[platformTab][1];
    root.innerHTML='<div class="loading small-loading">Carregando…</div>';
    try{
      if(platformTab==='monthly')await monthlyView(root,draw);
      else if(platformTab==='promos')await promosView(root,draw);
      else await summaryView(root,draw);
    }catch(e){if(e.status===401){location.href='/entrar';return;}root.innerHTML=empty('Não foi possível carregar',e.message,'<button id="platform-retry" class="btn secondary">Tentar novamente</button>');$('#platform-retry').onclick=draw;}
  }
  await draw();
}

async function monthlyView(root,draw){
  const r=await api('/api/platform/monthly?months=12'+(selectedMonth?'&month='+selectedMonth:''));
  selectedMonth=r.month;
  const index=r.months.findIndex(m=>m.month===r.month), m=r.months[index]||r.months[r.months.length-1], prev=r.months[index-1];
  const [label,format]=series[chartSeries];
  const values=r.months.map(x=>x[chartSeries]), top=Math.max(1,...values.map(v=>Math.abs(v)));
  const year=r.months.slice(-12).reduce((t,x)=>({gmv:t.gmv+x.gmv,received:t.received+x.received,orders:t.orders+x.orders}),{gmv:0,received:0,orders:0});
  root.innerHTML='<div class="metrics four">'+metric('Vendas das lojas • '+monthLong(m.month),money(m.gmv),m.month===r.months[r.months.length-1].month?'Mês em andamento':'')+metric('Pedidos concluídos',m.orders,'Ticket médio '+money(m.ticket))+metric('Recebido pela plataforma',money(m.received),'Despesas '+money(m.expenses))+metric('Resultado da plataforma',money(m.result),'Recebido − despesas')+'</div>'+
    '<div class="trend-row">'+change(m.gmv,prev?.gmv)+'<span class="muted">Lojas vendendo: <b>'+m.active_stores+'</b> • Lojas novas: <b>'+m.new_stores+'</b> • Cancelados: <b>'+m.cancelled+'</b> • Comissões geradas: <b>'+money(m.commission)+'</b></span></div>'+
    '<section class="panel"><div class="section-heading"><div><h2>'+label+' nos últimos 12 meses</h2><p class="muted">Clique em um mês para ver os detalhes e o ranking das lojas.</p></div><div class="chips">'+Object.entries(series).map(([k,[l]])=>'<button class="chip '+(k===chartSeries?'active':'')+'" data-series="'+k+'">'+l+'</button>').join('')+'</div></div>'+
    '<div class="chart month-chart" role="list">'+r.months.map(x=>'<button class="chart-column '+(x.month===r.month?'selected':'')+'" data-month="'+x.month+'" role="listitem" aria-label="'+monthLong(x.month)+': '+format(x[chartSeries])+'"><div class="chart-value">'+format(x[chartSeries])+'</div><div class="chart-bar '+(x[chartSeries]<0?'negative':'')+'" style="height:'+Math.max(2,Math.abs(x[chartSeries])/top*100)+'%"></div><small>'+monthName(x.month)+'</small></button>').join('')+'</div>'+
    '<div class="year-total"><span>Somando os 12 meses:</span><b>'+money(year.gmv)+'</b> em vendas das lojas • <b>'+year.orders+'</b> pedidos • <b>'+money(year.received)+'</b> recebidos pela plataforma</div></section>'+
    '<div class="overview-bottom"><section class="panel"><div class="section-heading"><div><h2>Ranking de '+monthLong(r.month)+'</h2><p class="muted">Lojas que mais venderam no mês.</p></div></div>'+
      (r.ranking.some(x=>x.orders)?table(['#','Loja','Pedidos','Vendas','Comissão','Pagou à plataforma'],r.ranking.filter(x=>x.orders||x.received).map((x,i)=>row([i+1,'<b>'+esc(x.name)+'</b>'+(x.enabled?'':' <span class="badge gray">Bloqueada</span>'),x.orders,money(x.gmv),money(x.commission),money(x.received)]))):'<p class="muted">Nenhuma venda concluída neste mês.</p>')+'</section>'+
    '<section class="panel"><div class="section-heading"><div><h2>Mês a mês</h2><p class="muted">Tabela completa para conferir ou levar para a planilha.</p></div><button id="export-months" class="btn secondary small">'+icon('copy')+' Exportar CSV</button></div>'+
      table(['Mês','Pedidos','Vendas das lojas','Ticket','Comissões','Recebido','Despesas','Resultado','Lojas ativas','Novas'],r.months.slice().reverse().map(x=>row(['<b>'+monthLong(x.month)+'</b>',x.orders,money(x.gmv),money(x.ticket),money(x.commission),money(x.received),money(x.expenses),money(x.result),x.active_stores,x.new_stores])))+'</section></div>';
  $$('[data-series]').forEach(b=>b.onclick=()=>{chartSeries=b.dataset.series;draw();});
  $$('[data-month]').forEach(b=>b.onclick=()=>{selectedMonth=b.dataset.month;draw();});
  $('#export-months').onclick=()=>{
    const lines=[['Mês','Pedidos','Vendas das lojas','Ticket médio','Comissões','Recebido','Despesas','Resultado','Lojas ativas','Lojas novas','Cancelados'].join(';'),
      ...r.months.map(x=>[x.month,x.orders,(x.gmv/100).toFixed(2),(x.ticket/100).toFixed(2),(x.commission/100).toFixed(2),(x.received/100).toFixed(2),(x.expenses/100).toFixed(2),(x.result/100).toFixed(2),x.active_stores,x.new_stores,x.cancelled].join(';'))];
    const link=document.createElement('a');link.href=URL.createObjectURL(new Blob(['﻿'+lines.join('\n')],{type:'text/csv'}));link.download='plataforma-mes-a-mes.csv';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  };
}

function health(x){
  const idle=daysSince(x.last_order), missing=Object.entries({products:'produtos',phone:'WhatsApp',pix:'Pix',address:'endereço'}).filter(([k])=>!x.setup[k]).map(([,v])=>v);
  const parts=[];
  if(idle===null)parts.push('<span class="badge gray">Nunca vendeu</span>');else if(idle>=7)parts.push('<span class="badge amber">Sem pedidos há '+idle+' dias</span>');else parts.push('<span class="badge green">Vendendo</span>');
  if(missing.length)parts.push('<small class="table-sub">Falta: '+missing.join(', ')+'</small>');
  return parts.join('');
}

async function summaryView(root,draw){
  const s=await api('/api/platform/summary?days='+period);
  if(platformTab==='history'){
    root.innerHTML='<section class="panel">'+(s.audit.length?s.audit.map(a=>'<div class="payment-line"><span>'+esc(auditLabel(a.action))+(a.detail&&['store.block','store.unblock'].includes(a.action)?' • '+esc(a.detail):'')+'</span><small>'+date(a.created_at)+'</small></div>').join(''):'<p class="muted">Nada registrado ainda.</p>')+'</section>';
    return;
  }
  if(platformTab==='cash'){
    root.innerHTML='<div class="page-toolbar">'+periods()+'<button id="new-ledger" class="btn">'+icon('plus')+' Registrar recebimento ou despesa</button></div><div class="metrics three">'+metric('Recebido pela plataforma',money(s.received),'Recebimentos registrados no período')+metric('Despesas da plataforma',money(s.expenses),'Gastos registrados no período')+metric('Resultado de caixa',money(s.cash_result),'Recebimentos − despesas')+'</div><section class="panel"><h2>Lançamentos</h2>'+table(['Loja','Tipo','Descrição','Valor','Data',''],s.ledger.map(l=>row([esc(l.store_name||'Plataforma'),l.kind==='receipt'?'Recebimento':'Despesa',esc(l.description),money(l.amount),date(l.created_at),l.voided_at?'<span class="badge gray">Anulado</span>':'<button class="btn secondary small" data-void-ledger="'+l.id+'">Anular</button>'])))+(!s.ledger.length?'<p class="muted">Registre um recebimento quando a loja pagar e uma despesa quando ocorrer um gasto.</p>':'')+'</section>';
    $$('[data-void-ledger]').forEach(b=>b.onclick=()=>{modal('Anular este lançamento?','<p>O valor sairá dos resultados. O lançamento e o registro de anulação permanecem no histórico.</p><button id="confirm-void" class="btn danger full">Anular lançamento</button>');$('#confirm-void').onclick=async()=>{try{await api('/api/platform/ledger/'+b.dataset.voidLedger,{method:'DELETE'});closeModal();toast('Lançamento anulado.');draw();}catch(e){toast(e.message);}};});
    bindPeriods(draw);$('#new-ledger').onclick=()=>ledgerDialog(s.stores,draw);return;
  }
  const blocked=s.stores.filter(x=>!x.enabled), overdue=s.stores.filter(x=>x.overdue), idle=s.stores.filter(x=>x.enabled&&(daysSince(x.last_order)??99)>=7);
  root.innerHTML='<div class="page-toolbar">'+periods()+'<label class="search compact">'+icon('search')+'<input id="platform-search" aria-label="Buscar loja" placeholder="Loja ou e-mail"></label></div><div class="metrics four">'+metric('Lojas cadastradas',s.stores.length,(s.stores.length-blocked.length)+' ativas • '+blocked.length+' bloqueadas')+metric('Mensalidades do mês',money(s.monthly_recurring),'Valor vigente, já com promoções')+metric('Mensalidades em aberto',money(s.overdue),overdue.length+' loja(s) sem pagamento registrado neste mês')+metric('Vendas dos lojistas',money(s.gross_store_sales),'Pedidos concluídos no período')+'</div>'+
    '<section class="panel"><div class="section-heading"><div><h2>Lojas</h2><p class="muted">Bloquear fecha a loja, impede novos pedidos e mostra o motivo no painel do lojista. O histórico é mantido.</p></div><div class="chips">'+[['all','Todas',s.stores.length],['overdue','Em aberto',overdue.length],['idle','Paradas',idle.length],['blocked','Bloqueadas',blocked.length]].map(([k,l,n])=>'<button class="chip '+(storeFilter===k?'active':'')+'" data-filter="'+k+'">'+l+' ('+n+')</button>').join('')+'</div></div><div id="platform-stores"></div></section>';
  function stores(){
    const term=$('#platform-search').value.toLowerCase();
    const list=s.stores.filter(x=>(x.name+' '+x.email).toLowerCase().includes(term)&&(storeFilter==='all'||(storeFilter==='overdue'&&x.overdue)||(storeFilter==='blocked'&&!x.enabled)||(storeFilter==='idle'&&idle.includes(x))));
    $('#platform-stores').innerHTML=list.length?table(['Loja','Situação','Mensalidade','Este mês','Vendas no período','Saúde',''],list.map(x=>row([
      '<b>'+esc(x.name)+'</b><small class="table-sub">'+esc(x.email)+'</small><a class="text-link small-link" href="/loja/'+esc(x.slug)+'" target="_blank" rel="noopener">Ver cardápio</a>',
      x.enabled?'<span class="badge green">Ativa</span>':'<span class="badge red">Bloqueada</span>'+(x.blocked_reason?'<small class="table-sub">'+esc(x.blocked_reason)+'</small>':''),
      money(x.effective_fee)+(x.promo_active?'<small class="table-sub promo-sub">Promoção'+(x.promo_label?' “'+esc(x.promo_label)+'”':'')+' até '+new Date(x.promo_until+'T12:00:00').toLocaleDateString('pt-BR')+' • normal '+money(x.monthly_fee)+'</small>':'')+(x.commission_bps?'<small class="table-sub">+ '+(x.commission_bps/100).toLocaleString('pt-BR')+'% de comissão</small>':''),
      !x.effective_fee?'<span class="muted">Sem mensalidade</span>':x.overdue?'<span class="badge amber">Em aberto</span><small class="table-sub">Pago '+money(x.received_month)+' de '+money(x.effective_fee)+'</small>':'<span class="badge green">Em dia</span>',
      money(x.revenue)+'<small class="table-sub">'+x.orders+' pedidos</small>',
      health(x),
      '<div class="row-actions"><button class="btn secondary small" data-plan="'+x.id+'">Contrato e promoção</button>'+(x.enabled?'<button class="btn secondary small danger-text" data-block="'+x.id+'">Bloquear</button>':'<button class="btn small" data-unblock="'+x.id+'">Desbloquear</button>')+(x.overdue?'<button class="btn secondary small" data-receive="'+x.id+'">Registrar pagamento</button>':'')+'</div>'
    ]))):'<p class="muted">Nenhuma loja neste filtro.</p>';
    $$('[data-plan]').forEach(b=>b.onclick=()=>planDialog(s.stores.find(x=>x.id===Number(b.dataset.plan)),draw));
    $$('[data-block]').forEach(b=>b.onclick=()=>blockDialog(s.stores.find(x=>x.id===Number(b.dataset.block)),draw));
    $$('[data-unblock]').forEach(b=>b.onclick=async()=>{try{await api('/api/platform/stores/'+b.dataset.unblock+'/block',{method:'POST',body:JSON.stringify({blocked:false,reason:''})});toast('Loja desbloqueada. O lojista já pode abrir a loja.');draw();}catch(e){toast(e.message);}});
    $$('[data-receive]').forEach(b=>b.onclick=()=>{const x=s.stores.find(v=>v.id===Number(b.dataset.receive));ledgerDialog(s.stores,draw,{store_id:x.id,amount:x.effective_fee-x.received_month,description:'Mensalidade '+monthLong(new Date().toISOString().slice(0,7))});});
  }
  stores();$('#platform-search').oninput=stores;bindPeriods(draw);
  $$('[data-filter]').forEach(b=>b.onclick=()=>{storeFilter=b.dataset.filter;$$('[data-filter]').forEach(c=>c.classList.toggle('active',c===b));stores();});
}

function blockDialog(s,done){
  modal('Bloquear '+s.name+'?','<form id="block-form"><p class="muted">A loja fecha na hora, para de receber pedidos e o lojista vê o motivo no painel. Nada é apagado e você pode desbloquear quando quiser.</p><label>Motivo (o lojista vai ver)<select id="block-preset" aria-label="Motivo pronto"><option value="Mensalidade em atraso.">Mensalidade em atraso</option><option value="Cadastro em análise pela plataforma.">Cadastro em análise</option><option value="Uso em desacordo com os termos da plataforma.">Uso em desacordo com os termos</option><option value="">Outro motivo…</option></select></label><label>Mensagem<textarea name="reason" required minlength="3" maxlength="300">Mensalidade em atraso.</textarea></label><p class="form-error" role="alert" hidden></p><button type="submit" class="btn danger full">Bloquear loja</button></form>');
  $('#block-preset').onchange=e=>{$('[name=reason]').value=e.target.value;$('[name=reason]').focus();};
  bindForm($('#block-form'),async form=>{await api('/api/platform/stores/'+s.id+'/block',{method:'POST',body:JSON.stringify({blocked:true,reason:form.get('reason')})});closeModal();toast('Loja bloqueada.');done();});
}

function planDialog(s,done){
  const until=new Date();until.setMonth(until.getMonth()+3);
  modal('Contrato de '+s.name,'<form id="plan-form"><p class="muted">A comissão vale para novos pedidos e incide sobre produtos após descontos. Nenhuma cobrança é executada automaticamente.</p><div class="form-grid">'+field('commission','Comissão (%)',s.commission_bps/100,'number','min="0" max="100" step=".01" required')+moneyInput('monthly','Mensalidade normal',s.monthly_fee)+'</div><fieldset class="promo-box"><legend>Mensalidade promocional</legend><label class="check-row"><span><input name="promo" type="checkbox" '+(s.promo_fee!=null?'checked':'')+'> Cobrar um valor promocional por um tempo</span></label><div class="form-grid">'+moneyInput('promo_fee','Valor na promoção',s.promo_fee??0,false)+field('promo_until','Vale até',s.promo_until||until.toISOString().slice(0,10),'date')+'</div>'+field('promo_label','Nome da promoção (opcional)',s.promo_label||'','text','maxlength="80" placeholder="Ex.: 3 meses pela metade"')+'<p class="muted">Use R$ 0,00 para meses grátis. Depois da data, volta a valer a mensalidade normal sozinha.</p></fieldset><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Salvar contrato</button></form>',true);
  bindForm($('#plan-form'),async form=>{
    const promo=form.has('promo');
    await api('/api/platform/stores/'+s.id,{method:'PUT',body:JSON.stringify({commission_bps:cents(form.get('commission')),monthly_fee:cents(form.get('monthly')),enabled:!!s.enabled,promo_fee:promo?cents(form.get('promo_fee')||0):null,promo_until:promo?form.get('promo_until'):'',promo_label:promo?form.get('promo_label'):''})});
    closeModal();toast('Contrato atualizado.');done();
  });
}

async function promosView(root,draw){
  const [{notices},s]=await Promise.all([api('/api/platform/notices'),api('/api/platform/summary?days=30')]);
  const promos=s.stores.filter(x=>x.promo_active);
  const kinds={promo:'Promoção',info:'Novidade',alert:'Aviso importante'};
  const today=new Date().toISOString().slice(0,10);
  root.innerHTML='<div class="overview-bottom"><section class="panel"><h2>Novo aviso para os lojistas</h2><p class="muted">Aparece no topo do painel de todas as lojas. Use para promoções, novidades e avisos de manutenção.</p><form id="notice-form"><label>Tipo<select name="kind" aria-label="Tipo"><option value="promo">Promoção</option><option value="info">Novidade</option><option value="alert">Aviso importante</option></select></label>'+field('title','Título','','text','required minlength="3" maxlength="100" placeholder="Ex.: Indique um amigo e ganhe 1 mês grátis"')+'<label>Mensagem<textarea name="body" required minlength="3" maxlength="600" placeholder="Explique a promoção e como participar."></textarea></label>'+field('expires','Mostrar até (opcional)','','date')+'<p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">'+icon('bell')+' Publicar aviso</button></form></section>'+
    '<section class="panel"><h2>Ideias de promoção</h2><p class="muted">Clique para preencher o aviso.</p><div class="idea-list">'+[
      ['promo','Indique e ganhe','Indique outra loja da cidade. Quando ela assinar, você ganha 1 mês grátis.'],
      ['promo','Primeiro mês grátis','Lojas novas não pagam a mensalidade do primeiro mês. Cadastre seus produtos e comece a vender hoje.'],
      ['promo','Plano anual com desconto','Pague 12 meses de uma vez e ganhe 2 meses grátis. Fale com o suporte.'],
      ['info','Dica: QR Code no balcão','Baixe o QR Code do seu cardápio em Configurações e coloque no balcão e na sacola de entrega.'],
      ['info','Novidade: taxa por bairro','Agora você pode cobrar a entrega por bairro. Veja em Configurações › Taxa por bairro.'],
      ['alert','Manutenção programada','O sistema pode ficar instável por alguns minutos no domingo de madrugada.']
    ].map(([k,t,b])=>'<button type="button" class="idea" data-kind="'+k+'" data-title="'+esc(t)+'" data-body="'+esc(b)+'"><b>'+esc(t)+'</b><span>'+esc(b)+'</span></button>').join('')+'</div></section></div>'+
    '<section class="panel"><h2>Avisos publicados</h2>'+(notices.length?table(['Aviso','Tipo','Validade','Situação',''],notices.map(n=>{const live=n.active&&(!n.expires||n.expires>=today);return row(['<b>'+esc(n.title)+'</b><small class="table-sub">'+esc(n.body)+'</small>',kinds[n.kind],n.expires?new Date(n.expires+'T12:00:00').toLocaleDateString('pt-BR'):'Sem validade',live?'<span class="badge green">No ar</span>':'<span class="badge gray">'+(n.active?'Vencido':'Desativado')+'</span>','<button class="btn secondary small" data-notice="'+n.id+'" data-active="'+(n.active?0:1)+'">'+(n.active?'Desativar':'Reativar')+'</button>']);})):'<p class="muted">Nenhum aviso publicado ainda.</p>')+'</section>'+
    '<section class="panel"><div class="section-heading"><div><h2>Lojas com mensalidade promocional</h2><p class="muted">Para dar uma promoção, abra Lojas e contas › Contrato e promoção.</p></div><button id="go-stores" class="btn secondary small">Ir para lojas '+icon('arrow')+'</button></div>'+(promos.length?table(['Loja','Promoção','Valor','Normal','Até'],promos.map(x=>row(['<b>'+esc(x.name)+'</b>',esc(x.promo_label||'—'),money(x.effective_fee),money(x.monthly_fee),new Date(x.promo_until+'T12:00:00').toLocaleDateString('pt-BR')]))):'<p class="muted">Nenhuma loja com promoção ativa.</p>')+'</section>';
  $$('.idea').forEach(b=>b.onclick=()=>{const f=$('#notice-form');$('[name=kind]',f).value=b.dataset.kind;$('[name=title]',f).value=b.dataset.title;$('[name=body]',f).value=b.dataset.body;$('[name=title]',f).focus();});
  $$('[data-notice]').forEach(b=>b.onclick=async()=>{try{await api('/api/platform/notices/'+b.dataset.notice,{method:'PATCH',body:JSON.stringify({active:b.dataset.active==='1'})});toast('Aviso atualizado.');draw();}catch(e){toast(e.message);}});
  $('#go-stores').onclick=()=>{platformTab='stores';draw();};
  bindForm($('#notice-form'),async form=>{await api('/api/platform/notices',{method:'POST',body:JSON.stringify({kind:form.get('kind'),title:form.get('title'),body:form.get('body'),expires:form.get('expires')||''})});toast('Aviso publicado para todos os lojistas.');draw();});
}

function ledgerDialog(stores,done,prefill={}){
  const key=crypto.randomUUID();
  modal('Lançamento da plataforma','<form id="ledger-form"><label>Tipo<select name="kind" aria-label="Tipo"><option value="receipt">Recebimento de loja</option><option value="expense">Despesa da plataforma</option></select></label><label>Loja<select name="store_id" aria-label="Loja"><option value="">Plataforma (somente despesas)</option>'+stores.map(s=>'<option value="'+s.id+'" '+(prefill.store_id===s.id?'selected':'')+'>'+esc(s.name)+'</option>').join('')+'</select></label>'+field('description','Descrição',prefill.description||'','text','required minlength="3" maxlength="200"')+moneyInput('amount','Valor',prefill.amount||0)+'<p class="muted">Registre apenas valores efetivamente recebidos ou gastos. Isso não cobra o cliente nem movimenta uma conta bancária.</p><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Registrar lançamento</button></form>');
  bindForm($('#ledger-form'),async form=>{await api('/api/platform/ledger',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({kind:form.get('kind'),store_id:form.get('store_id')?Number(form.get('store_id')):null,description:form.get('description'),amount:cents(form.get('amount'))})});closeModal();toast('Lançamento registrado.');done();});
}
