import { $, $$, icon, brand, money, esc, image, api, modal, closeModal, bindForm, empty, toast, pay, date, attachFallbacks, copy, cents, optionPrice, fromPrice, hasChoices, optionLabels, validIds, optionFields, readOptions, bindOptionLimits } from './ui.js';
let catalog, cart=[], selected='all', search='', orderKey='', activeSlug='';
const cartKey=()=> 'sca.cart.'+catalog.store.id;
const days=['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'];
const whatsapp=phone=>'https://wa.me/'+phone.replace(/\D/g,'').replace(/^(?!55)/,'55');
const zones=()=>catalog.store.delivery_zones||[];
const canOrder=()=>catalog.store.open_now||(catalog.store.allow_scheduling&&catalog.store.open);
const savedCustomer=()=>{try{return JSON.parse(localStorage.getItem('sca.customer')||'{}');}catch{return {};}};
function slotOptions(){
  const out=[],now=new Date();
  for(let i=0;i<7;i++){const day=new Date(now.getFullYear(),now.getMonth(),now.getDate()+i);const value=day.getFullYear()+'-'+String(day.getMonth()+1).padStart(2,'0')+'-'+String(day.getDate()).padStart(2,'0');
    out.push('<option value="'+value+'">'+(i===0?'Hoje':i===1?'Amanhã':day.toLocaleDateString('pt-BR',{weekday:'long'}))+' • '+day.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'})+'</option>');}
  return out.join('');
}
const deliveryLabel=s=>zones().length?'Entrega a partir de '+money(Math.min(...zones().map(z=>z.fee))):'Entrega '+money(s.delivery_fee);
function hoursList(s){
  if(!s.auto_hours)return '';
  return '<div class="hours-list"><b>Horário de funcionamento</b>'+days.map((name,i)=>{const shifts=s.hours[String(i)]||[];return '<div><span>'+name+'</span><span>'+(shifts.length?shifts.map(x=>x[0]+' às '+x[1]).join(' • '):'Fechado')+'</span></div>';}).join('')+'</div>';
}
const total=()=>cart.reduce((sum,line)=>sum+line.quantity*line.unit,0);
const count=()=>cart.reduce((sum,line)=>sum+line.quantity,0);
function persist(){try{localStorage.setItem(cartKey(),JSON.stringify(cart));}catch{}updateBar();}
function loadCart(){
  try{const saved=JSON.parse(localStorage.getItem(cartKey())||'[]');cart=Array.isArray(saved)?saved.filter(x=>x&&typeof x.id==='string'&&Number.isInteger(x.quantity)&&x.quantity>0&&x.quantity<=50&&Array.isArray(x.option_ids)).slice(0,50):[];}catch{cart=[];}
  cart=cart.flatMap(line=>{
    const product=catalog.products.find(x=>x.id===line.product_id);
    if(!product||product.stock===0)return [];
    const ids=validIds(product,line.option_ids);
    return [{...line,name:product.name,image:product.image,unit:optionPrice(product,ids),option_ids:ids,extras:optionLabels(product,ids).map(name=>({name}))}];
  });persist();
}
export async function renderMenu(slug){
  activeSlug=slug;catalog=await api('/api/store/'+encodeURIComponent(slug));document.title=catalog.store.name+' • SeuComércioAqui';
  loadCart();
  const s=catalog.store;
  document.documentElement.style.setProperty('--shop-color',s.color);
  $('#app').innerHTML='<div class="shop"><header class="shop-top">'+brand()+'<a class="text-link" href="/entrar">Sou lojista '+icon('arrow')+'</a></header><main id="main"><div class="shop-cover" style="background-color:'+esc(s.color)+'"><img src="'+esc(image(s.banner))+'" alt="" fetchpriority="high"><div class="cover-shade"></div><span class="cover-label">FEITO AQUI. PEDIDO POR VOCÊ.</span></div><section class="store-summary"><img class="store-logo" src="'+esc(image(s.logo))+'" alt="'+esc(s.name)+'"><div class="store-title"><span class="badge '+(s.open_now?'green':'gray')+'"><i></i>'+esc(s.status_text)+'</span><h1>'+esc(s.name)+'</h1><p>'+esc(s.description||'Escolha seus favoritos. A gente cuida do resto.')+'</p><div class="store-meta"><span>'+icon('clock')+esc(s.delivery_minutes)+'</span><span>'+icon('truck')+deliveryLabel(s)+'</span>'+(s.minimum_order?'<span>Mínimo '+money(s.minimum_order)+'</span>':'')+'</div></div><button id="store-info" class="btn secondary small">'+icon('pin')+' Informações</button></section>'+
  (!s.open_now?'<div class="notice">'+esc(s.status_text)+'. '+(s.allow_scheduling&&s.open?'Você já pode <b>agendar</b> seu pedido para quando abrirmos.':'Você pode conhecer o cardápio e voltar quando abrirmos.')+'</div>':'')+
  '<div class="menu-toolbar"><label class="search"><span class="sr-only">Buscar produto</span>'+icon('search')+'<input id="menu-search" type="search" placeholder="O que você quer pedir?"></label><div id="categories" class="chips"><button class="chip active" data-cat="all">Destaques</button>'+catalog.categories.map(c=>'<button class="chip" data-cat="'+c.id+'">'+esc(c.name)+'</button>').join('')+'<button class="chip" data-cat="other">Outros</button></div></div><section class="menu-section"><div class="section-heading"><div><span class="eyebrow">ESCOLHA O SEU FAVORITO</span><h2 id="menu-title">Nosso cardápio</h2></div><span id="product-count" class="muted"></span></div><div id="product-list" class="product-grid"></div></section><div class="shop-end">'+brand()+'<p>O sabor é da loja. A facilidade é por aqui.</p><p class="legal-links"><a href="/termos">Termos</a> • <a href="/privacidade">Privacidade</a></p></div></main><div id="cart-bar" class="cart-bar"></div></div>';
  $('#menu-search').addEventListener('input',e=>{search=e.target.value.trim().toLocaleLowerCase('pt-BR');renderList();});
  $$('[data-cat]').forEach(button=>button.onclick=()=>{
    selected=button.dataset.cat;$$('[data-cat]').forEach(b=>b.classList.toggle('active',b===button));
    $('#menu-title').textContent=selected==='all'?'Nosso cardápio':selected==='other'?'Outros produtos':catalog.categories.find(c=>String(c.id)===selected)?.name||'Cardápio';renderList();
  });
  $('#store-info').onclick=()=>modal('Sobre a loja','<div class="store-info"><h3>'+esc(s.name)+'</h3><p>'+esc(s.description)+'</p><p>'+icon('pin')+esc(s.address||'Endereço ainda não informado.')+'</p><p>'+icon('clock')+'Estimativa: '+esc(s.delivery_minutes)+'</p>'+(zones().length?'<div class="hours-list"><b>Taxa de entrega por bairro</b>'+zones().map(z=>'<div><span>'+esc(z.name)+'</span><span>'+money(z.fee)+'</span></div>').join('')+'</div>':'<p>Entrega: '+money(s.delivery_fee)+' • Retirada sem taxa</p>')+hoursList(s)+'<p>Pagamentos: '+s.payments.map(p=>pay[p]).join(', ')+'</p>'+(s.phone?'<a class="btn full" href="'+whatsapp(s.phone)+'" target="_blank" rel="noopener">Falar com a loja</a>':'')+'</div>');
  renderList();updateBar();attachFallbacks();
}
function renderList(){
  const list=catalog.products.filter(p=>(selected==='all'||(selected==='other'?!p.category_id:String(p.category_id)===selected))&&(!search||(p.name+' '+p.description).toLocaleLowerCase('pt-BR').includes(search)));
  $('#product-count').textContent=list.length+' opções';
  $('#product-list').innerHTML=list.length?list.map(p=>'<article class="product-card '+(p.stock===0?'sold-out':'')+'"><button class="product-open" data-product="'+p.id+'" aria-label="Ver '+esc(p.name)+'"><div class="product-photo"><img src="'+esc(image(p.image))+'" alt="'+esc(p.name)+'" loading="lazy">'+(p.featured?'<span class="product-stamp">DA CASA</span>':'')+(p.stock===0?'<span class="sold-stamp">Esgotado</span>':'')+'</div><div class="product-copy"><h3>'+esc(p.name)+'</h3><p>'+esc(p.description)+'</p><div><strong>'+(hasChoices(p)?'<small class="from">a partir de</small> ':'')+money(fromPrice(p))+'</strong><span class="plus-circle">'+icon('plus')+'</span></div></div></button></article>').join(''):empty('Nada por aqui ainda',search?'Tente buscar outro nome.':'A loja está preparando esta parte do cardápio.');
  $$('[data-product]').forEach(button=>button.onclick=()=>productDialog(catalog.products.find(p=>p.id===Number(button.dataset.product))));
  attachFallbacks($('#product-list'));
}
function updateBar(){
  const bar=$('#cart-bar');if(!bar)return;
  bar.innerHTML='<button class="cart-trigger" id="open-cart"><span class="cart-count">'+count()+'</span><span>'+icon('bag')+' '+(count()?'Ver minha sacola':'Sua sacola está vazia')+'</span><strong>'+money(total())+'</strong>'+icon('arrow')+'</button>';
  $('#open-cart').onclick=cartDialog;
}
function productDialog(product){
  let quantity=1;
  const d=modal(product.name,'<div class="product-detail"><img src="'+esc(image(product.image))+'" alt="'+esc(product.name)+'"><p>'+esc(product.description)+'</p><strong class="detail-price">'+(hasChoices(product)?'A partir de ':'')+money(fromPrice(product))+'</strong></div><form id="add-form">'+optionFields(product)+
  '<label>Alguma observação?<textarea name="notes" maxlength="200" placeholder="Ex.: sem cebola"></textarea></label><div class="quantity-submit"><div class="quantity"><button type="button" id="qty-less" class="icon-btn" aria-label="Diminuir quantidade">'+icon('minus')+'</button><output id="quantity">1</output><button type="button" id="qty-more" class="icon-btn" aria-label="Aumentar quantidade">'+icon('plus')+'</button></div><button class="btn" type="submit" '+(!canOrder()||product.stock===0?'disabled':'')+'>Adicionar • <span id="add-price">'+money(fromPrice(product))+'</span></button></div><p class="form-error" role="alert" hidden></p></form>');
  const calculate=()=>{const {ids}=readOptions(d,product);$('#quantity').textContent=quantity;$('#add-price').textContent=money((ids.length||!hasChoices(product)?optionPrice(product,ids):fromPrice(product))*quantity);const err=$('#add-form .form-error');err.hidden=true;};
  $('#qty-less').onclick=()=>{quantity=Math.max(1,quantity-1);calculate();};
  $('#qty-more').onclick=()=>{quantity=Math.min(50,product.stock??50,quantity+1);calculate();};
  bindOptionLimits(d,product,'',calculate);
  $('#add-form').onsubmit=e=>{
    e.preventDefault();
    if(!canOrder()||product.stock===0)return;
    const {ids:option_ids,error}=readOptions(d,product);
    if(error){const err=$('#add-form .form-error');err.textContent=error;err.hidden=false;err.scrollIntoView({block:'nearest',behavior:'smooth'});return;}
    cart.push({id:crypto.randomUUID(),product_id:product.id,name:product.name,image:product.image,quantity,option_ids,extras:optionLabels(product,option_ids).map(name=>({name})),notes:$('[name=notes]',d).value,unit:optionPrice(product,option_ids)});
    orderKey='';persist();closeModal();toast('Adicionado à sacola!');
  };attachFallbacks(d);
}
function cartDialog(){
  const d=modal('Sua sacola',cart.length?'<div class="cart-lines">'+cart.map(line=>'<article class="cart-line"><img src="'+esc(image(line.image))+'" alt=""><div><b>'+esc(line.name)+'</b><small>'+line.extras.map(x=>esc(x.name)).join(', ')+'</small>'+(line.notes?'<small>'+esc(line.notes)+'</small>':'')+'<strong>'+money(line.unit*line.quantity)+'</strong></div><div class="quantity"><button class="icon-btn" data-less="'+line.id+'" aria-label="Diminuir '+esc(line.name)+'">'+icon('minus')+'</button><span>'+line.quantity+'</span><button class="icon-btn" data-more="'+line.id+'" aria-label="Aumentar '+esc(line.name)+'">'+icon('plus')+'</button></div></article>').join('')+'</div><div class="total-row"><span>Subtotal</span><b>'+money(total())+'</b></div><p class="muted">Taxa de entrega e cupons são calculados na próxima etapa.</p><button id="checkout" class="btn full" '+(!canOrder()?'disabled':'')+'>Continuar pedido '+icon('arrow')+'</button>':empty('Sua sacola está esperando','Escolha algo gostoso no cardápio.'));
  $$('[data-less]',d).forEach(b=>b.onclick=()=>{const line=cart.find(x=>x.id===b.dataset.less);line.quantity--;cart=cart.filter(x=>x.quantity>0);orderKey='';persist();cartDialog();});
  $$('[data-more]',d).forEach(b=>b.onclick=()=>{const line=cart.find(x=>x.id===b.dataset.more);line.quantity=Math.min(50,line.quantity+1);orderKey='';persist();cartDialog();});
  if($('#checkout',d))$('#checkout',d).onclick=checkoutDialog;
  attachFallbacks(d);
}
function itemPayload(){return cart.map(x=>({product_id:x.product_id,quantity:x.quantity,option_ids:x.option_ids,notes:x.notes||''}));}
function checkoutDialog(){
  const s=catalog.store;
  const d=modal('Finalize seu pedido','<form id="checkout-form"><fieldset><legend>Como você quer receber?</legend><div class="choice-row"><label><input type="radio" name="mode" value="delivery" checked> '+icon('truck')+' Entrega</label><label><input type="radio" name="mode" value="pickup"> '+icon('store')+' Retirada</label></div></fieldset>'+(s.allow_scheduling?'<fieldset><legend>Quando?</legend><div class="choice-row"><label><input type="radio" name="when" value="now" '+(s.open_now?'checked':'disabled')+'> '+icon('clock')+' Agora</label><label><input type="radio" name="when" value="later" '+(s.open_now?'':'checked')+'> '+icon('clock')+' Agendar</label></div><div id="schedule-fields" class="form-grid '+(s.open_now?'hidden':'')+'"><label>Dia<select name="schedule_day">'+slotOptions()+'</select></label><label>Horário<input type="time" name="schedule_time" step="900"></label></div></fieldset>':'')+'<div class="form-grid"><label>Seu nome<input name="customer" autocomplete="name" minlength="2" maxlength="100" required></label><label>WhatsApp com DDD<input name="phone" type="tel" autocomplete="tel" minlength="10" maxlength="20" placeholder="(19) 99999-9999" required></label></div>'+(zones().length?'<label id="zone-label">Seu bairro<select name="zone" required><option value="">Escolha o bairro</option>'+zones().map(z=>'<option value="'+esc(z.name)+'">'+esc(z.name)+' • '+money(z.fee)+'</option>').join('')+'</select></label>':'')+'<label id="cep-label">CEP (opcional, preenche o endereço)<input name="cep" inputmode="numeric" autocomplete="postal-code" maxlength="9" placeholder="00000-000"></label><label id="address-label">Endereço completo<textarea name="address" autocomplete="street-address" minlength="8" maxlength="400" placeholder="Rua, número, bairro e referência" required></textarea></label><label>Como vai pagar?<select name="payment">'+s.payments.map(p=>'<option value="'+p+'">'+pay[p]+'</option>').join('')+'</select></label><div id="pix-note" class="notice '+(s.payments[0]==='pix'?'':'hidden')+'">Pix com confirmação manual. A chave e as instruções aparecem depois do pedido.</div><label id="change-label" class="hidden">Troco para quanto? (opcional)<input name="change_for" type="number" min="0" step=".01" placeholder="Ex.: 100,00"></label><label>Cupom de desconto<div class="inline-input"><input name="coupon" maxlength="30" placeholder="Digite seu cupom"><button class="btn secondary" type="button" id="apply-coupon">Aplicar</button></div></label><label>Observações do pedido<textarea name="notes" maxlength="500" placeholder="Algum detalhe para a loja?"></textarea></label><div id="checkout-totals" class="checkout-totals"></div><p class="form-error" role="alert" hidden></p><label class="check-row remember"><span><input type="checkbox" name="remember" checked> Lembrar meus dados neste aparelho</span></label><p class="checkout-consent">Ao confirmar, seu nome, telefone e endereço serão enviados à loja para atender este pedido. <a href="/privacidade" target="_blank">Privacidade</a></p><button class="btn full" type="submit">Confirmar pedido '+icon('check')+'</button></form>',true);
  let quote=null,version=0;
  const form=$('#checkout-form'),mode=()=> $('[name=mode]:checked',form).value;
  const scheduledFor=()=>$('[name=when]:checked',form)?.value==='later'&&form.schedule_day.value&&form.schedule_time.value?form.schedule_day.value+'T'+form.schedule_time.value:'';
  const saved=savedCustomer();['customer','phone','address','cep'].forEach(k=>{if(saved[k]&&form[k])form[k].value=saved[k];});
  if(saved.zone&&$('[name=zone]',form)&&[...$('[name=zone]',form).options].some(o=>o.value===saved.zone))$('[name=zone]',form).value=saved.zone;
  $$('[name=when]',form).forEach(r=>r.onchange=()=>{$('#schedule-fields').classList.toggle('hidden',r.value!=='later'||!r.checked);refreshQuote();});
  if(form.schedule_day){form.schedule_day.onchange=refreshQuote;form.schedule_time.onchange=refreshQuote;}
  form.phone.addEventListener('change',refreshQuote);
  form.cep.addEventListener('input',async()=>{
    const digits=form.cep.value.replace(/\D/g,'');if(digits.length!==8)return;
    try{const r=await fetch('https://viacep.com.br/ws/'+digits+'/json/');const c=await r.json();if(c.erro)return toast('CEP não encontrado.');
      form.address.value=[c.logradouro,'Nº ',c.bairro,c.localidade+'/'+c.uf].filter(Boolean).join(', ');
      const zone=$('[name=zone]',form);if(zone&&c.bairro){const match=[...zone.options].find(o=>o.value&&o.value.toLocaleLowerCase('pt-BR')===c.bairro.toLocaleLowerCase('pt-BR'));if(match){zone.value=match.value;refreshQuote();}}
      form.address.focus();form.address.setSelectionRange(form.address.value.indexOf('Nº ')+3,form.address.value.indexOf('Nº ')+3);
    }catch{toast('Não foi possível buscar o CEP agora. Digite o endereço.');}
  });
  async function refreshQuote(){
    const v=++version;quote=null;
    $('#checkout-totals',d).textContent='Calculando o total…';
    try{const result=await api('/api/store/'+encodeURIComponent(activeSlug)+'/quote',{method:'POST',body:JSON.stringify({items:itemPayload(),mode:mode(),zone:mode()==='delivery'?$('[name=zone]',form)?.value||'':'',scheduled_for:scheduledFor(),phone:form.phone.value.trim(),coupon:$('[name=coupon]',form).value.trim()})});if(v!==version||!d.open)return;quote=result;
      $('#checkout-totals',d).innerHTML='<div><span>Produtos</span><b>'+money(result.subtotal)+'</b></div><div><span>'+(mode()==='delivery'?'Entrega'+(result.zone?' • '+esc(result.zone):''):'Retirada')+'</span><b>'+money(result.delivery_fee)+'</b></div>'+(result.discount-result.loyalty_discount?'<div class="discount"><span>Desconto</span><b>− '+money(result.discount-result.loyalty_discount)+'</b></div>':'')+(result.loyalty_discount?'<div class="discount"><span>Prêmio de fidelidade</span><b>− '+money(result.loyalty_discount)+'</b></div>':'')+'<div class="total-row"><span>Total do pedido</span><strong>'+money(result.total)+'</strong></div>'+(result.loyalty&&!result.loyalty.available?'<p class="loyalty-hint">'+icon('tag')+' Faltam <b>'+result.loyalty.remaining+'</b> pedido'+(result.loyalty.remaining>1?'s':'')+' para ganhar '+money(result.loyalty.reward)+' de desconto.</p>':'');
    }catch(error){if(v!==version)return;$('#checkout-totals',d).innerHTML='<p class="form-error">'+esc(error.message)+'</p>';}
  }
  $$('[name=mode]',form).forEach(input=>input.onchange=()=>{const delivery=mode()==='delivery';$('#address-label').classList.toggle('hidden',!delivery);$('#cep-label').classList.toggle('hidden',!delivery);$('[name=address]',form).required=delivery;if($('#zone-label')){$('#zone-label').classList.toggle('hidden',!delivery);$('[name=zone]',form).required=delivery;}refreshQuote();});
  if($('[name=zone]',form))$('[name=zone]',form).onchange=refreshQuote;
  $('[name=payment]',form).onchange=e=>{$('#pix-note').classList.toggle('hidden',e.target.value!=='pix');$('#change-label').classList.toggle('hidden',e.target.value!=='cash');};
  $('#apply-coupon').onclick=refreshQuote;
  $('[name=coupon]',form).oninput=()=>{quote=null;$('#checkout-totals',d).textContent='Aplique o cupom para atualizar o total.';};
  bindForm(form,async formData=>{
    if(!quote){await refreshQuote();if(!quote)throw new Error('Confira os itens e o cupom antes de confirmar.');}
    if($('[name=when]:checked',form)?.value==='later'&&!scheduledFor())throw new Error('Escolha o dia e o horário do agendamento.');
    const {cep,schedule_day,schedule_time,when,remember,...fields}=Object.fromEntries(formData);
    const body={...fields,zone:mode()==='delivery'?formData.get('zone')||'':'',scheduled_for:scheduledFor(),items:itemPayload(),mode:mode(),expected_total:quote.total,change_for:formData.get('change_for')?cents(formData.get('change_for')):null};
    // A new payload gets a fresh key. Network retries of the same payload reuse it.
    const serialized=JSON.stringify(body);if(orderKey.payload!==serialized)orderKey={payload:serialized,key:crypto.randomUUID()};
    let result;
    try{result=await api('/api/store/'+encodeURIComponent(activeSlug)+'/orders',{method:'POST',headers:{'Idempotency-Key':orderKey.key},body:serialized});}
    catch(error){if(error.status===409)await refreshQuote();throw error;}
    try{if(formData.has('remember'))localStorage.setItem('sca.customer',JSON.stringify({customer:fields.customer,phone:fields.phone,address:fields.address,cep,zone:body.zone}));else localStorage.removeItem('sca.customer');}catch{}
    cart=[];persist();location.href='/pedido/'+result.token;
  });$('[name=payment]',form).dispatchEvent(new Event('change'));refreshQuote();
}
function orderMessage(o,s){
  const lines=o.items.map(i=>'• '+i.quantity+'x '+i.name+(i.extras.length?' ('+i.extras.map(x=>x.name).join(', ')+')':'')+(i.notes?' — '+i.notes:''));
  return ['Olá, '+s.name+'! Acabei de fazer o pedido #'+o.number+' pelo cardápio digital:','',...lines,'',
    (o.mode==='delivery'?'Entrega'+(o.zone?' • '+o.zone:''):'Retirada na loja')+' • '+pay[o.payment],...(o.scheduled_for?['Agendado para '+new Date(o.scheduled_for).toLocaleString('pt-BR',{weekday:'long',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})]:[]),'Total: '+money(o.total),'','Acompanhar: '+location.href].join('\n');
}
export async function renderTracking(token){
  let timer;
  async function refresh(){
    const {order:o,store:s}=await api('/api/track/'+encodeURIComponent(token));
    document.title='Pedido #'+o.number+' • '+s.name;
    const flow=o.mode==='delivery'?['new','preparing','ready','delivering','completed']:['new','preparing','ready','completed'];
    const current=flow.indexOf(o.status);
    $('#app').innerHTML='<div class="tracking"><header class="shop-top">'+brand()+'<a class="text-link" href="/loja/'+esc(s.slug)+'">Voltar à loja '+icon('arrow')+'</a></header><main id="main"><div class="tracking-hero"><span class="tracking-check">'+icon(o.status==='cancelled'?'close':'check')+'</span><span class="eyebrow">PEDIDO #'+o.number+'</span><h1>'+(o.status==='new'?'Seu pedido chegou!':o.status==='cancelled'?'Pedido cancelado':o.status==='completed'?'Tudo certo por aqui.':o.status_label)+'</h1><p>'+esc(s.name)+' está cuidando do seu pedido.</p><span class="badge '+(o.paid?'green':'gray')+'">'+(o.paid?'Pagamento confirmado':'Pagamento aguardando confirmação')+'</span></div>'+
      (o.status!=='cancelled'?'<div class="timeline">'+flow.map((status,i)=>'<div class="'+(i<=current?'done':'')+'"><span>'+icon(i<current?'check':i===current?'clock':'bag')+'</span><small>'+({new:'Recebido',preparing:'Em preparo',ready:'Pronto',delivering:'Em entrega',completed:'Concluído'}[status])+'</small></div>').join('')+'</div>':'<div class="notice">Entre em contato com a loja para mais informações sobre o cancelamento.</div>')+
      (o.payment==='pix'&&!o.paid&&o.status!=='cancelled'?'<section class="panel pix-panel"><div>'+icon('wallet')+'<h2>Pague com Pix</h2></div><p>Chave Pix da loja</p><div class="pix-key"><code>'+esc(s.pix_key||'Entre em contato com a loja para obter a chave.')+'</code>'+(s.pix_key?'<button id="copy-pix" class="btn secondary small">'+icon('copy')+' Copiar</button>':'')+'</div><p class="muted">Envie '+money(o.total)+'. A loja confere o pagamento e confirma aqui. Não é uma cobrança automática.</p></section>':'')+
      '<section class="panel"><div class="section-heading"><h2>Seu pedido</h2><span class="muted">'+date(o.created_at)+'</span></div>'+o.items.map(item=>'<div class="tracking-item"><div><b>'+item.quantity+' × '+esc(item.name)+'</b><small>'+item.extras.map(x=>esc(x.name)).join(', ')+(item.notes?' • '+esc(item.notes):'')+'</small></div><strong>'+money(item.quantity*item.unit_price)+'</strong></div>').join('')+'<div class="checkout-totals"><div><span>Produtos</span><b>'+money(o.subtotal)+'</b></div><div><span>'+(o.mode==='delivery'?'Entrega':'Retirada na loja')+'</span><b>'+money(o.delivery_fee)+'</b></div>'+(o.discount?'<div><span>Desconto</span><b>− '+money(o.discount)+'</b></div>':'')+'<div class="total-row"><span>Total</span><strong>'+money(o.total)+'</strong></div></div><p class="muted">'+pay[o.payment]+'</p></section>'+
      '<section class="tracking-footer"><p>Esta página se atualiza automaticamente.<br>Guarde o link para acompanhar seu pedido.</p>'+(s.phone?'<a class="btn secondary" target="_blank" rel="noopener" href="'+whatsapp(s.phone)+'?text='+encodeURIComponent('Olá! Gostaria de falar sobre o pedido #'+o.number)+'">Falar com a loja '+icon('arrow')+'</a>':'')+'</section></main></div>';
    if(o.motoboy&&['ready','delivering'].includes(o.status))$('.tracking-hero').insertAdjacentHTML('beforeend','<p class="scheduled-note">'+icon('truck')+' Motoboy: <b>'+esc(o.motoboy)+'</b>'+(o.tracking_url?' • <a class="text-link" href="'+esc(o.tracking_url)+'" target="_blank" rel="noopener">ver no mapa</a>':'')+'</p>');
    if(o.scheduled_for)$('.tracking-hero').insertAdjacentHTML('beforeend','<p class="scheduled-note">'+icon('clock')+' Agendado para <b>'+new Date(o.scheduled_for).toLocaleString('pt-BR',{weekday:'long',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+'</b></p>');
    if(o.status==='completed'&&o.rating==null)$('.tracking-footer').insertAdjacentHTML('beforebegin','<section class="panel review-panel"><h2>Como foi o seu pedido?</h2><form id="review-form"><div class="stars" role="radiogroup" aria-label="Nota de 1 a 5">'+[1,2,3,4,5].map(n=>'<label><input type="radio" name="rating" value="'+n+'" required><span aria-hidden="true">★</span><span class="sr-only">'+n+' estrela'+(n>1?'s':'')+'</span></label>').join('')+'</div><label>Quer contar algo? (opcional)<textarea name="comment" maxlength="500"></textarea></label><p class="form-error" role="alert" hidden></p><button class="btn" type="submit">Enviar avaliação</button></form></section>');
    if(o.rating!=null)$('.tracking-footer').insertAdjacentHTML('beforebegin','<p class="review-done">Obrigado pela avaliação: '+'★'.repeat(o.rating)+'</p>');
    if(['completed','cancelled'].includes(o.status))$('.tracking-footer').insertAdjacentHTML('afterbegin','<button id="reorder" class="btn">'+icon('bag')+' Pedir de novo</button>');
    if($('#review-form'))bindForm($('#review-form'),async f=>{await api('/api/track/'+encodeURIComponent(token)+'/review',{method:'POST',body:JSON.stringify({rating:Number(f.get('rating')),comment:f.get('comment')||''})});toast('Obrigado pela avaliação!');refresh();});
    if($('#reorder'))$('#reorder').onclick=()=>{try{const key='sca.cart.'+s.id;const current=JSON.parse(localStorage.getItem(key)||'[]');o.items.forEach(i=>current.push({id:crypto.randomUUID(),product_id:i.product_id,quantity:i.quantity,option_ids:i.extras.map(x=>x.id).filter(Boolean),notes:i.notes||''}));localStorage.setItem(key,JSON.stringify(current.slice(0,50)));}catch{}location.href='/loja/'+encodeURIComponent(s.slug);};
    if(o.loyalty)$('.tracking-footer').insertAdjacentHTML('beforebegin','<section class="panel loyalty-card"><h2>'+icon('tag')+' Cartão fidelidade</h2><div class="loyalty-dots">'+Array.from({length:o.loyalty.goal},(_,i)=>'<span class="'+(o.loyalty.available||i<o.loyalty.completed%o.loyalty.goal?'on':'')+'"></span>').join('')+'</div><p>'+(o.loyalty.available?'Você já ganhou <b>'+money(o.loyalty.reward)+'</b> de desconto: ele entra sozinho no próximo pedido.':'Faltam <b>'+o.loyalty.remaining+'</b> pedido'+(o.loyalty.remaining>1?'s':'')+' concluído'+(o.loyalty.remaining>1?'s':'')+' para ganhar '+money(o.loyalty.reward)+' de desconto.')+'</p>'+(o.loyalty_discount?'<p class="muted">Neste pedido você usou '+money(o.loyalty_discount)+' de prêmio.</p>':'')+'</section>');
    if(s.phone&&o.status==='new')$('.tracking-hero').insertAdjacentHTML('beforeend','<a class="btn whatsapp-send" target="_blank" rel="noopener" href="'+whatsapp(s.phone)+'?text='+encodeURIComponent(orderMessage(o,s))+'">Enviar pedido no WhatsApp da loja '+icon('arrow')+'</a><small class="muted whatsapp-hint">Opcional: avisa a loja na hora pelo WhatsApp.</small>');
    if(o.payment==='pix_online'&&!o.paid&&o.status!=='cancelled'&&o.pix){$('.tracking-hero').insertAdjacentHTML('afterend','<section class="panel pix-panel"><h2>Pague com Pix</h2>'+(o.pix.code&&!o.pix.expired?'<img class="pix-qr" src="/api/track/'+encodeURIComponent(token)+'/pix.svg" alt="QR Code Pix" width="220" height="220"><div class="pix-key"><code>'+esc(o.pix.code)+'</code><button id="copy-pix-online" class="btn secondary small">'+icon('copy')+' Copia e cola</button></div><p class="muted">Pague '+money(o.total)+'. A confirmação é automática e aparece aqui.</p>':'<p class="muted">O código Pix expirou ou não foi gerado.</p><button id="renew-pix" class="btn">Gerar novo Pix</button>')+'</section>');
      if($('#copy-pix-online'))$('#copy-pix-online').onclick=()=>copy(o.pix.code);
      if($('#renew-pix'))$('#renew-pix').onclick=async()=>{try{await api('/api/track/'+encodeURIComponent(token)+'/pix',{method:'POST'});refresh();}catch(e){toast(e.message);}};}
    if($('#copy-pix'))$('#copy-pix').onclick=()=>copy(s.pix_key);
    if(!['completed','cancelled'].includes(o.status))timer=setTimeout(()=>refresh().catch(()=>{toast('Não foi possível atualizar agora.');timer=setTimeout(()=>refresh().catch(()=>{}),15000);}),12000);
  }
  await refresh();window.addEventListener('pagehide',()=>clearTimeout(timer),{once:true});
}
