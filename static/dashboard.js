import { $, $$, icon, brand, money, esc, image, api, auth, modal, closeModal, bindForm, empty, toast, pay, date, attachFallbacks, copy, cents, field, moneyInput, statuses } from './ui.js';
let store, products=[], categories=[], drivers=[], orders=[], tab='overview', period=7, timer, generation=0;
export async function renderDashboard(){
  store=(await api('/api/admin/store')).store;document.title='Painel • '+store.name;
  $('#app').innerHTML='<div class="dashboard"><header class="dashboard-head">'+brand()+'<nav class="dashboard-nav">'+[['overview','Visão geral'],['orders','Pedidos'],['products','Cardápio'],['drivers','Entregas'],['sales','Vendas']].map(([id,label])=>'<button data-tab="'+id+'">'+label+'</button>').join('')+'</nav><div class="head-actions"><button class="icon-btn" data-tab="settings" aria-label="Configurações">'+icon('gear')+'</button><button id="logout" class="icon-btn" aria-label="Sair">'+icon('logout')+'</button></div></header><main id="main" class="dashboard-main"><section class="dashboard-title"><div><span class="eyebrow" id="page-kicker">SEU COMÉRCIO EM MOVIMENTO</span><h1 id="page-title">Seu dia em um olhar</h1><p id="page-subtitle">Tudo pronto para vender mais.</p></div><div class="title-actions"><button id="store-toggle" class="badge '+(store.open?'green':'gray')+'"><i></i>'+(store.open?'Loja aberta':'Loja fechada')+'</button><a class="btn" href="/loja/'+esc(store.slug)+'" target="_blank" rel="noopener">Ver minha loja '+icon('eye')+'</a></div></section><section id="dashboard-content" aria-live="polite"></section></main><footer class="dashboard-footer"><span>SeuComércioAqui</span><span>'+esc(store.name)+' • '+esc(auth.user.name)+'</span></footer></div>';
  $$('[data-tab]').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
  $('#logout').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'});location.href='/entrar';}catch(e){toast(e.message);}};
  $('#store-toggle').onclick=async()=>{try{const result=await api('/api/admin/store',{method:'PUT',body:JSON.stringify({...store,open:!store.open})});store=result.store;updateStoreButton();toast(store.open?'Loja aberta para pedidos.':'Loja fechada.');}catch(e){toast(e.message);}};
  await switchTab('overview');
}
function updateStoreButton(){const b=$('#store-toggle');b.className='badge '+(store.open?'green':'gray');b.innerHTML='<i></i>'+(store.open?'Loja aberta':'Loja fechada');}
async function switchTab(next,quiet=false){
  clearTimeout(timer);tab=next;const v=++generation;
  const titles={overview:['Seu dia em um olhar','Os pedidos e números que importam agora.'],orders:['Cada pedido, no seu tempo','Do primeiro clique à última entrega.'],products:['Seu cardápio, sua assinatura','Organize seus produtos e deixe tudo com a sua cara.'],drivers:['Entrega bem cuidada','Sua equipe e os pedidos a caminho.'],sales:['Os números do seu negócio','Acompanhe vendas, recebimentos e despesas.'],settings:['A sua loja, do seu jeito','Identidade, contato e operação em um só lugar.']};
  $('#page-title').textContent=titles[tab][0];$('#page-subtitle').textContent=titles[tab][1];$$('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  if(!quiet)$('#dashboard-content').innerHTML='<div class="loading small-loading">Carregando…</div>';
  try{
    if(tab==='overview'||tab==='orders'){
      const [result,team,today,week]=await Promise.all([api('/api/admin/orders'),api('/api/admin/drivers'),api('/api/admin/summary?days=1'),api('/api/admin/summary?days=7')]);
      if(v!==generation)return;orders=result.orders;drivers=team.drivers;
      if(tab==='overview')overview(today,week);else ordersPage();
      timer=setTimeout(()=>{if(!document.hidden)switchTab(tab,true);else timer=setTimeout(()=>switchTab(tab,true),12000);},12000);
    }else if(tab==='products'){
      const result=await api('/api/admin/products');if(v!==generation)return;products=result.products;categories=result.categories;productsPage();
    }else if(tab==='drivers'){
      const [result,team]=await Promise.all([api('/api/admin/orders'),api('/api/admin/drivers')]);if(v!==generation)return;orders=result.orders;drivers=team.drivers;driversPage();
    }else if(tab==='sales'){
      const summary=await api('/api/admin/summary?days='+period);if(v!==generation)return;salesPage(summary);
    }else settingsPage();
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
  $('#all-orders').onclick=()=>switchTab('orders');$('#share-store').onclick=()=>copy(location.origin+'/loja/'+store.slug);bindOrderButtons();
}
function orderBoard(list){
  return '<div class="order-board">'+[['new','Novos'],['preparing','Em preparo'],['ready','Prontos'],['delivering','Em entrega']].map(([status,label])=>{
    const filtered=list.filter(o=>o.status===status);
    return '<section class="order-lane lane-'+status+'"><h3><i></i>'+label+' <span>'+filtered.length+'</span></h3>'+filtered.map(orderCard).join('')+(!filtered.length?'<p class="lane-empty">Tudo em dia por aqui.</p>':'')+'</section>';
  }).join('')+'</div>';
}
function nextStatus(order){return {new:'preparing',preparing:'ready',ready:order.mode==='delivery'?'delivering':'completed',delivering:'completed'}[order.status];}
function actionLabel(order){return {new:'Aceitar pedido',preparing:'Marcar pronto',ready:order.mode==='delivery'?'Saiu para entrega':'Concluir retirada',delivering:'Concluir entrega'}[order.status];}
function orderCard(o){
  const minutes=Math.max(0,Math.round((Date.now()-new Date(o.created_at).getTime())/60000));
  return '<article class="order-card"><button class="order-detail" data-detail="'+o.id+'" aria-label="Ver pedido '+o.number+'"><div class="order-top"><b>#'+o.number+'</b><small>'+ (minutes<60?'há '+minutes+' min':date(o.created_at))+'</small></div><div class="order-customer"><span class="avatar">'+esc(o.customer.split(' ').slice(0,2).map(x=>x[0]).join('').toUpperCase())+'</span><div><b>'+esc(o.customer)+'</b><small>'+esc(o.items.map(x=>x.quantity+' × '+x.name).join(', '))+'</small></div></div><div class="order-meta"><span class="badge tiny">'+icon(o.mode==='delivery'?'truck':'bag')+(o.mode==='delivery'?'Entrega':'Retirada')+'</span><strong>'+money(o.total)+'</strong></div></button>'+ (nextStatus(o)?'<button class="btn small full order-next '+(o.status==='preparing'?'lime':'')+'" data-next="'+o.id+'">'+actionLabel(o)+'</button>':'')+'</article>';
}
function bindOrderButtons(){
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
  const d=modal('Pedido #'+o.number,'<div class="order-dialog-top"><div><h3>'+esc(o.customer)+'</h3><p>'+esc(o.phone)+' • '+date(o.created_at)+'</p><span class="badge">'+statuses[o.status]+'</span></div><button id="print-order" class="btn secondary small">'+icon('print')+' Imprimir</button></div><div class="notice">'+icon(o.mode==='delivery'?'truck':'store')+' '+(o.mode==='delivery'?'Entrega: '+esc(o.address):'Retirada no balcão')+'</div>'+o.items.map(x=>'<div class="tracking-item"><div><b>'+x.quantity+' × '+esc(x.name)+'</b><small>'+x.extras.map(e=>esc(e.name)).join(', ')+'</small><small>'+esc(x.notes)+'</small></div><b>'+money(x.unit_price*x.quantity)+'</b></div>').join('')+
  (o.notes?'<p class="notice">Observações: '+esc(o.notes)+'</p>':'')+'<div class="checkout-totals"><div><span>Produtos</span><b>'+money(o.subtotal)+'</b></div><div><span>Entrega</span><b>'+money(o.delivery_fee)+'</b></div><div><span>Desconto</span><b>− '+money(o.discount)+'</b></div><div class="total-row"><span>Total</span><strong>'+money(o.total)+'</strong></div></div><p>'+pay[o.payment]+(o.change_for?' • Troco para '+money(o.change_for):'')+'</p><form id="order-update">'+
  '<label class="check-row"><span><input name="paid" type="checkbox" '+(o.paid?'checked':'')+' '+(o.status==='cancelled'?'disabled':'')+'>Pagamento confirmado</span></label>'+
  (o.mode==='delivery'?'<label>Entregador<select name="driver_id"><option value="">Sem entregador</option>'+drivers.filter(x=>x.active||x.id===o.driver_id).map(x=>'<option value="'+x.id+'" '+(x.id===o.driver_id?'selected':'')+'>'+esc(x.name)+'</option>').join('')+'</select></label>':'')+
  '<p class="form-error" role="alert" hidden></p><div class="dialog-actions"><button class="btn" type="submit">Salvar atualização</button><button class="btn secondary" id="copy-track" type="button">'+icon('link')+' Link do pedido</button></div></form>'+
  (!['completed','cancelled'].includes(o.status)?'<button id="cancel-order" class="text-danger">Cancelar pedido</button>':'')+'<details class="help"><summary>Histórico do pedido</summary>'+o.events.map(e=>'<p>'+statuses[e.status]+' • '+date(e.created_at)+'</p>').join('')+'</details>',true);
  $('#print-order').onclick=()=>window.print();$('#copy-track').onclick=()=>copy(location.origin+'/pedido/'+o.tracking_token);
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
  const d=modal(p?'Editar produto':'Novo produto','<form id="product-form"><div class="form-grid">'+field('name','Nome do produto',p?.name||'','text','required minlength="2" maxlength="120"')+moneyInput('price','Preço',p?.price||0)+'</div><label>Descrição<textarea name="description" maxlength="500" placeholder="Ingredientes e o que torna esse produto especial">'+esc(p?.description||'')+'</textarea></label><div class="form-grid"><label>Categoria<select name="category_id"><option value="">Outros</option>'+categories.map(c=>'<option value="'+c.id+'" '+(p?.category_id===c.id?'selected':'')+'>'+esc(c.name)+'</option>').join('')+'</select></label>'+field('stock','Estoque (vazio = sem controle)',p?.stock??'','number','min="0" step="1"')+'</div>'+uploadField('image','Foto do produto',p?.image||'')+'<div class="check-options"><label><input type="checkbox" name="active" '+(!p||p.active?'checked':'')+'> Disponível no cardápio</label><label><input type="checkbox" name="featured" '+(p?.featured?'checked':'')+'> Destaque da casa</label></div><fieldset><legend>Complementos opcionais <small>Até 12 opções</small></legend><div id="extra-rows"></div><button type="button" id="add-extra" class="text-link">'+icon('plus')+' Adicionar complemento</button></fieldset>'+field('position','Ordem de exibição',p?.position||0,'number','min="0" step="1"')+'<p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Salvar produto</button></form>',true);
  const extras=structuredClone(p?.extras||[]);
  function drawExtras(){
    $('#extra-rows').innerHTML=extras.map((x,i)=>'<div class="extra-row"><input aria-label="Nome do complemento '+(i+1)+'" data-extra-name="'+i+'" placeholder="Ex.: queijo extra" value="'+esc(x.name)+'" maxlength="80" required><input aria-label="Preço do complemento '+(i+1)+'" data-extra-price="'+i+'" type="number" min="0" step=".01" value="'+(x.price/100).toFixed(2)+'" required><button type="button" class="icon-btn" data-remove-extra="'+i+'" aria-label="Remover complemento">'+icon('close')+'</button></div>').join('');
    $$('[data-extra-name]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraName)].name=x.value);
    $$('[data-extra-price]',d).forEach(x=>x.oninput=()=>extras[Number(x.dataset.extraPrice)].price=cents(x.value));
    $$('[data-remove-extra]',d).forEach(x=>x.onclick=()=>{extras.splice(Number(x.dataset.removeExtra),1);drawExtras();});
  }
  $('#add-extra').onclick=()=>{if(extras.length>=12)return toast('Use até 12 opções.');extras.push({id:crypto.randomUUID(),name:'',price:0});drawExtras();};drawExtras();bindUploads(d);
  bindForm($('#product-form'),async form=>{
    const value={name:form.get('name'),description:form.get('description'),price:cents(form.get('price')),category_id:form.get('category_id')?Number(form.get('category_id')):null,stock:form.get('stock')===''?null:Number(form.get('stock')),image:form.get('image'),active:form.has('active'),featured:form.has('featured'),position:Number(form.get('position')),extras};
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
  $('#dashboard-content').innerHTML='<div class="page-toolbar"><div class="chips">'+[[1,'Hoje'],[7,'7 dias'],[30,'30 dias']].map(([value,label])=>'<button class="chip '+(period===value?'active':'')+'" data-period="'+value+'">'+label+'</button>').join('')+'</div><div class="toolbar-actions"><a class="btn secondary" href="/api/admin/export">'+icon('chart')+' Exportar pedidos</a><button class="btn" id="new-expense">'+icon('plus')+' Nova despesa</button></div></div><div class="metrics four">'+metric('Vendas concluídas',money(summary.revenue),'chart')+metric('Recebido',money(summary.received),'wallet')+metric('Despesas',money(summary.expenses_total),'wallet')+metric('Saldo de recebimentos',money(summary.balance),'wallet')+'</div><div class="sales-grid"><section class="panel"><div class="section-heading"><h2>Vendas do período</h2><span>'+summary.completed+' concluídos</span></div>'+chart(summary.chart)+'</section><section class="panel"><h2>Por forma de pagamento</h2>'+summary.payments.map(p=>'<div class="payment-line"><span>'+pay[p.method]+'</span><strong>'+money(p.total)+'</strong></div>').join('')+'<div class="notice"><div>Aguardando pagamento <b>'+money(summary.pending_payment)+'</b></div><small>Vendas consideram pedidos concluídos. Recebimentos consideram os pagamentos confirmados, inclusive pedidos em andamento.</small></div></section></div><section class="panel"><div class="section-heading"><h2>Despesas registradas</h2><span class="muted">'+summary.expenses.length+' lançamentos</span></div>'+(summary.expenses.length?'<div class="table-wrap"><table><thead><tr><th>Descrição</th><th>Data</th><th>Valor</th><th><span class="sr-only">Ações</span></th></tr></thead><tbody>'+summary.expenses.map(e=>'<tr><td>'+esc(e.description)+'</td><td>'+date(e.created_at)+'</td><td>'+money(e.amount)+'</td><td><button class="icon-btn" data-delete-expense="'+e.id+'" aria-label="Excluir despesa">'+icon('close')+'</button></td></tr>').join('')+'</tbody></table></div>':empty('Nenhuma despesa no período','Registre os gastos para acompanhar o saldo.'))+'</section>';
  $$('[data-period]').forEach(b=>b.onclick=()=>{period=Number(b.dataset.period);switchTab('sales');});
  $('#new-expense').onclick=expenseEditor;
  $$('[data-delete-expense]').forEach(b=>b.onclick=()=>{modal('Excluir esta despesa?','<p>O lançamento será removido do período.</p><button id="confirm-delete" class="btn danger full">Excluir despesa</button>');$('#confirm-delete').onclick=async()=>{try{await api('/api/admin/expenses/'+b.dataset.deleteExpense,{method:'DELETE'});closeModal();switchTab('sales');}catch(e){toast(e.message);}};});
}
function expenseEditor(){
  modal('Nova despesa','<form id="expense-form">'+field('description','Descrição','','text','required minlength="2" maxlength="200"')+moneyInput('amount','Valor')+'<p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">Registrar despesa</button></form>');
  bindForm($('#expense-form'),async form=>{await api('/api/admin/expenses',{method:'POST',body:JSON.stringify({description:form.get('description'),amount:cents(form.get('amount'))})});closeModal();toast('Despesa registrada.');switchTab('sales');});
}
function settingsPage(){
  $('#dashboard-content').innerHTML='<form id="store-form"><section class="panel"><div class="section-heading"><div><h2>Identidade da loja</h2><p class="muted">A marca que seus clientes conhecem.</p></div><span class="feature-icon">'+icon('store')+'</span></div><div class="form-grid">'+field('name','Nome do comércio',store.name,'text','required minlength="2" maxlength="100"')+field('color','Cor principal',store.color,'color')+'</div><label>Descrição<textarea name="description" maxlength="500">'+esc(store.description)+'</textarea></label><div class="form-grid">'+uploadField('logo','Logo',store.logo)+uploadField('banner','Capa do cardápio',store.banner)+'</div><div class="notice">Seu link: <b>'+esc(location.origin+'/loja/'+store.slug)+'</b> <button class="text-link" type="button" id="settings-copy">'+icon('copy')+' Copiar</button></div></section><section class="panel"><h2>Contato e entrega</h2><div class="form-grid">'+field('phone','WhatsApp com DDD',store.phone,'tel','maxlength="20"')+field('delivery_minutes','Estimativa de entrega',store.delivery_minutes,'text','required maxlength="40"')+'</div><label>Endereço da loja<textarea name="address" maxlength="400">'+esc(store.address)+'</textarea></label><div class="form-grid">'+moneyInput('delivery_fee','Taxa de entrega',store.delivery_fee)+moneyInput('minimum_order','Pedido mínimo em produtos',store.minimum_order)+'</div></section><section class="panel"><h2>Pagamentos</h2><p class="muted">Pix é confirmado pela loja. Cartão é cobrado na entrega ou retirada.</p><div class="check-options">'+Object.entries(pay).map(([value,label])=>'<label><input name="payments" type="checkbox" value="'+value+'" '+(store.payments.includes(value)?'checked':'')+'> '+label+'</label>').join('')+'</div>'+field('pix_key','Chave Pix',store.pix_key,'text','maxlength="200"')+'</section><p class="form-error" role="alert" hidden></p><div class="settings-save"><button class="btn" type="submit">Salvar configurações '+icon('check')+'</button><button id="change-password" class="btn secondary" type="button">Alterar senha</button></div></form>';
  bindUploads($('#store-form'));$('#settings-copy').onclick=()=>copy(location.origin+'/loja/'+store.slug);$('#change-password').onclick=passwordDialog;
  bindForm($('#store-form'),async form=>{
    const value={...store,name:form.get('name'),description:form.get('description'),phone:form.get('phone'),address:form.get('address'),delivery_minutes:form.get('delivery_minutes'),color:form.get('color'),logo:form.get('logo'),banner:form.get('banner'),delivery_fee:cents(form.get('delivery_fee')),minimum_order:cents(form.get('minimum_order')),payments:form.getAll('payments'),pix_key:form.get('pix_key')};
    store=(await api('/api/admin/store',{method:'PUT',body:JSON.stringify(value)})).store;toast('Sua loja foi atualizada.');updateStoreButton();
  });
}
function passwordDialog(){
  modal('Alterar sua senha','<form id="password-form">'+field('current_password','Senha atual','','password','required autocomplete="current-password"')+field('new_password','Nova senha','','password','required minlength="10" maxlength="128" autocomplete="new-password"')+'<p class="muted">As outras sessões serão encerradas.</p><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">Alterar senha</button></form>');
  bindForm($('#password-form'),async form=>{await api('/api/auth/password',{method:'PUT',body:JSON.stringify(Object.fromEntries(form))});closeModal();toast('Senha alterada.');});
}
