export const $ = (s, root=document) => root.querySelector(s);
export const $$ = (s, root=document) => [...root.querySelectorAll(s)];
export const money = value => new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format((value||0)/100);
export const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const date = value => new Date(value).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
export const cents = value => Math.round(Number(String(value).replace(',','.'))*100);
export const image = value => value || '/static/placeholder.svg';
export const icons = {
  arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>', back:'<path d="m14 6-6 6 6 6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>', minus:'<path d="M5 12h14"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>', bag:'<path d="M5 7h14l1 14H4L5 7Z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check:'<path d="m5 12 4 4L19 6"/>', chart:'<path d="M5 20V12m7 8V4m7 16V8"/>',
  truck:'<path d="M3 5h12v12H3V5Zm12 5h4l3 4v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
  pin:'<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
  gear:'<path d="m9 3-1 3-3 1v4l-2 1 2 2v4l3 1 1 3h6l1-3 3-1v-4l2-2-2-1V7l-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
  link:'<path d="m10 14 4-4m-6 7-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2-1 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" transform="translate(1 0)"/>',
  edit:'<path d="m4 16 12-12 4 4L8 20H4v-4Zm9-9 4 4"/>',
  logout:'<path d="M10 3H4v18h6m3-14 5 5-5 5m-4-5h12"/>',
  wallet:'<rect x="3" y="6" width="18" height="14" rx="3"/><path d="M3 8V5l14-2v3m-1 7h5m-5 4h5"/>',
  store:'<path d="M4 9v12h16V9M3 9l2-6h14l2 6c-2 3-4 3-6 0-2 3-4 3-6 0-2 3-4 3-6 0Zm6 12v-7h6v7"/>',
  bell:'<path d="M5 17h14l-2-4V9a5 5 0 0 0-10 0v4l-2 4Zm5 4h4"/>',
  tag:'<path d="M3 3h8l10 10-8 8L3 11V3Z"/><circle cx="7" cy="7" r="1"/>',
  print:'<path d="M6 9V3h12v6M6 17H3V9h18v8h-3M6 14h12v7H6v-7Z"/>',
  copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  user:'<circle cx="12" cy="7" r="4"/><path d="M4 21v-3a8 8 0 0 1 16 0v3"/>'
};
export const icon = name => '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+(icons[name]||icons.store)+'</svg>';
export const brand = () => '<a class="brand" href="/" aria-label="SeuComércioAqui, início"><img src="/static/logo.svg" alt="" width="40" height="40"><span>SeuComércio<b>Aqui</b><small>Seu negócio. Mais perto.</small></span></a>';
export const statuses = {new:'Novo',preparing:'Em preparo',ready:'Pronto',delivering:'Em entrega',completed:'Concluído',cancelled:'Cancelado'};
export const pay = {pix:'Pix',cash:'Dinheiro',card:'Cartão na entrega/retirada'};
export let auth = {csrf:'',user:null,registration:true};
export async function bootstrap(){Object.assign(auth,await api('/api/session'));}
export async function api(url,options={}){
  const headers = {...options.headers};
  if(options.body && !(options.body instanceof FormData))headers['Content-Type']='application/json';
  if(options.method && !['GET','HEAD'].includes(options.method))headers['X-CSRF-Token']=auth.csrf;
  let response;
  try{response=await fetch(url,{...options,headers,credentials:'same-origin'});}catch{throw new Error('Sem conexão. Confira sua internet e tente novamente.');}
  const data=await response.json().catch(()=>({error:'Resposta inválida do servidor.'}));
  if(!response.ok){const error=new Error(data.error||'Não foi possível concluir.');error.status=response.status;throw error;}
  if(data.csrf)auth.csrf=data.csrf;
  return data;
}
export function toast(message){
  const el=$('#toast');el.textContent=message;el.classList.add('show');
  clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),4500);
}
export function modal(title,html,wide=false){
  const el=$('#modal');if(el.open)el.close();
  el.className=wide==='drawer'?'drawer':wide?'wide':'';
  el.innerHTML='<div class="dialog-head"><h2 id="modal-title">'+esc(title)+'</h2><button class="icon-btn" data-close aria-label="Fechar">'+icon('close')+'</button></div>'+html;
  el.showModal();$('[data-close]',el).addEventListener('click',()=>el.close());
  el.onclick=e=>{if(e.target===el)el.close();};
  return el;
}
export function closeModal(){$('#modal').close();}
export function bindForm(form,handler){
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(form.dataset.busy)return;
    const button=$('button[type=submit]',form);const original=button?.innerHTML;
    form.dataset.busy='1';if(button){button.disabled=true;button.textContent='Aguarde…';}
    const error=$('.form-error',form);if(error){error.textContent='';error.hidden=true;}
    try{await handler(new FormData(form),form);}catch(err){if(error){error.textContent=err.message;error.hidden=false;}else toast(err.message);}
    finally{delete form.dataset.busy;if(button){button.disabled=false;button.innerHTML=original;}}
  });
}
export function empty(title,description,action=''){
  return '<div class="empty">'+icon('bag')+'<h3>'+esc(title)+'</h3><p>'+esc(description)+'</p>'+action+'</div>';
}
export async function copy(value){
  try{await navigator.clipboard.writeText(value);toast('Copiado!');}
  catch{modal('Copie o link','<input readonly value="'+esc(value)+'" aria-label="Link para copiar"><p class="muted">Selecione o texto e copie.</p>');}
}
export function attachFallbacks(root=document){
  $$('img',root).forEach(el=>{
    const fallback=()=>{if(!el.src.endsWith('/static/placeholder.svg'))el.src='/static/placeholder.svg';};
    el.addEventListener('error',fallback,{once:true});
    if(el.complete&&el.naturalWidth===0)fallback();
  });
}
export function moneyInput(name,label,value=0,required=true){
 return '<label>'+esc(label)+'<div class="money-input"><span>R$</span><input name="'+esc(name)+'" aria-label="'+esc(label)+'" type="number" step="0.01" min="0" '+(required?'required':'')+' value="'+(value/100).toFixed(2)+'"></div></label>';
}
export function field(name,label,value='',type='text',attrs=''){
 return '<label>'+esc(label)+'<input name="'+esc(name)+'" type="'+type+'" value="'+esc(value)+'" '+attrs+'></label>';
}

// Escolhas do produto (variações e complementos). O servidor confere tudo de novo.
const groupsOf = p => p.option_groups || [];
export function optionPrice(p, ids){
  const set = new Set(ids); let price = p.price;
  p.extras.forEach(x => { if(set.has(x.id)) price += x.price; });
  groupsOf(p).forEach(g => { const picked = g.options.filter(o => set.has(o.id)); if(!picked.length) return;
    price += g.pricing === 'max' ? Math.max(...picked.map(o => o.price)) : picked.reduce((s, o) => s + o.price, 0); });
  return price;
}
export function fromPrice(p){
  let price = p.price;
  groupsOf(p).forEach(g => { if(!g.min) return; const prices = g.options.map(o => o.price).sort((a, b) => a - b);
    price += g.pricing === 'max' ? prices[0] : prices.slice(0, g.min).reduce((s, v) => s + v, 0); });
  return price;
}
export const hasChoices = p => groupsOf(p).some(g => g.min > 0);
export function optionLabels(p, ids){
  const set = new Set(ids), names = [];
  groupsOf(p).forEach(g => g.options.forEach(o => { if(set.has(o.id)) names.push(g.name + ': ' + o.name); }));
  p.extras.forEach(x => { if(set.has(x.id)) names.push(x.name); });
  return names;
}
export function validIds(p, ids){
  const known = new Set([...p.extras.map(x => x.id), ...groupsOf(p).flatMap(g => g.options.map(o => o.id))]);
  return ids.filter(id => known.has(id));
}
function groupHint(g){
  const rule = g.min === g.max ? 'Escolha ' + g.min : g.min ? 'Escolha de ' + g.min + ' a ' + g.max : 'Escolha até ' + g.max;
  return (g.min ? '<span class="req">Obrigatório</span>' : '<span class="opt">Opcional</span>') + rule + (g.pricing === 'max' && g.max > 1 ? ' • cobra o de maior valor' : '');
}
export function optionFields(p, prefix=''){
  return groupsOf(p).map(g => '<fieldset class="option-group" data-group="' + esc(g.id) + '"><legend>' + esc(g.name) + '<small>' + groupHint(g) + '</small></legend>' +
    g.options.map(o => '<label class="check-row"><span><input type="' + (g.max === 1 ? 'radio' : 'checkbox') + '" name="' + prefix + 'g_' + esc(g.id) + '" value="' + esc(o.id) + '">' + esc(o.name) + '</span>' + (o.price ? '<b>' + (g.pricing === 'max' || (g.min && !p.price) ? '' : '+ ') + money(o.price) + '</b>' : '') + '</label>').join('') + '</fieldset>').join('') +
    (p.extras.length ? '<fieldset class="option-group"><legend>Adicionais<small><span class="opt">Opcional</span></small></legend>' + p.extras.map(x => '<label class="check-row"><span><input type="checkbox" name="' + prefix + 'extras" value="' + esc(x.id) + '">' + esc(x.name) + '</span><b>+ ' + money(x.price) + '</b></label>').join('') + '</fieldset>' : '');
}
export function readOptions(root, p, prefix=''){
  const ids = []; let error = '';
  groupsOf(p).forEach(g => { const picked = $$('input[name="' + prefix + 'g_' + g.id + '"]:checked', root).map(x => x.value); ids.push(...picked);
    if(!error && (picked.length < g.min || picked.length > g.max)) error = g.name + ': ' + (g.min === g.max ? 'escolha ' + g.min : picked.length < g.min ? 'escolha pelo menos ' + g.min : 'escolha até ' + g.max) + '.'; });
  ids.push(...$$('input[name="' + prefix + 'extras"]:checked', root).map(x => x.value));
  return {ids, error};
}
export function bindOptionLimits(root, p, prefix='', onChange=()=>{}){
  groupsOf(p).forEach(g => $$('input[name="' + prefix + 'g_' + g.id + '"]', root).forEach(input => input.addEventListener('change', () => {
    const checked = $$('input[name="' + prefix + 'g_' + g.id + '"]:checked', root);
    if(g.max > 1 && checked.length > g.max){ input.checked = false; toast('Em ' + g.name + ' você pode escolher até ' + g.max + '.'); }
    onChange();
  })));
  $$('input[name="' + prefix + 'extras"]', root).forEach(x => x.addEventListener('change', onChange));
}
