import { $, $$, api, esc, money, bindForm, toast, empty } from './ui.js';
import { matchesSearch } from './search.js';

export async function contextualSuggestions(parent){
  const root=document.createElement('div');root.dataset.management='marketing';parent.append(root);
  const [settings,initialReport]=await Promise.all([api('/api/admin/marketing/combinations'),api('/api/admin/marketing/combinations/report')]);
  if(!root.isConnected||root.dataset.management!=='marketing')return;
  const products=settings.products;
  root.insertAdjacentHTML('beforeend','<section class="panel combination-panel"><div class="section-heading"><div><span class="eyebrow">UMA BOA COMBINAÇÃO</span><h2>Sugestões por produto</h2></div><span class="badge green">Até 6 por produto</span></div><p class="muted">Depois de adicionar um produto, o cliente vê as combinações escolhidas por você. Ele decide o que levar e escolhe os complementos antes de adicionar.</p><div class="combination-layout"><form id="combination-form"><label>Produto principal<select name="source" aria-label="Produto principal" required><option value="">Escolha um produto</option>'+products.map(p=>'<option value="'+p.id+'">'+esc(p.name)+(p.active?'':' (inativo)')+'</option>').join('')+'</select></label><div id="combination-editor" hidden><label>Buscar produto para oferecer<input type="search" id="combination-search" placeholder="Ex.: bebida, batata..."></label><div id="combination-options" class="combination-options"></div><h3>Ordem das sugestões <small id="combination-count"></small></h3><ol id="combination-selected" class="combination-selected"></ol><p class="muted">Itens esgotados, indisponíveis neste horário ou já na sacola ficam de fora. Sem combinações disponíveis, continuam valendo as sugestões gerais da sacola.</p><p class="form-error" role="alert" hidden></p><button class="btn" type="submit">Salvar combinações</button><p id="combination-status" class="muted" role="status"></p></div></form><aside class="combination-example"><span class="eyebrow">NO CARDÁPIO DO CLIENTE</span><h3 id="combination-example-title">Escolha o produto principal</h3><p>Adicionado à sacola. Que tal completar?</p><div id="combination-preview"></div><small>Prévia da ordem. Preços e disponibilidade são conferidos no pedido.</small></aside></div></section><section class="panel"><div class="section-heading"><div><span class="eyebrow">RESULTADO DAS COMBINAÇÕES</span><h2>O que suas sugestões venderam</h2></div><label>Período<select id="combination-days"><option value="7">Últimos 7 dias</option><option value="30" selected>Últimos 30 dias</option><option value="90">Últimos 90 dias</option></select></label></div><p class="muted">Pedidos criados no período que já foram concluídos. Somente itens adicionados pelas combinações por produto, com o produto principal presente no pedido. Valor bruto dos itens e complementos, antes de descontos; não inclui frete nem representa lucro ou dinheiro recebido.</p><div id="combination-report" aria-live="polite"></div></section>');
  const form=$('#combination-form',root),source=form.elements.source;
  let selected=[],dirty=false,loadingReport=0;
  const name=id=>products.find(p=>p.id===id)?.name||'Produto removido';
  const status=message=>{$('#combination-status',root).textContent=message;};
  function draw(){
    const query=$('#combination-search',root).value;
    const options=products.filter(p=>p.active&&p.id!==Number(source.value)&&!selected.includes(p.id)&&matchesSearch(query,[p.name]));
    $('#combination-options',root).innerHTML=options.length?options.map(p=>'<button type="button" class="btn secondary small" data-combine="'+p.id+'" '+(selected.length>=6?'disabled':'')+'>+ '+esc(p.name)+'</button>').join(''):'<p class="muted">Nenhum outro produto disponível nesta busca.</p>';
    $('#combination-count',root).textContent=selected.length+'/6';
    $('#combination-selected',root).innerHTML=selected.length?selected.map((id,i)=>'<li><span>'+esc(name(id))+(products.find(p=>p.id===id)?.active?'':' <small>(inativo ou removido)</small>')+'</span><div><button type="button" class="icon-btn" data-move="'+i+'" data-step="-1" aria-label="Subir '+esc(name(id))+'" '+(!i?'disabled':'')+'>↑</button><button type="button" class="icon-btn" data-move="'+i+'" data-step="1" aria-label="Descer '+esc(name(id))+'" '+(i===selected.length-1?'disabled':'')+'>↓</button><button type="button" class="btn secondary small" data-remove="'+id+'" aria-label="Remover '+esc(name(id))+'">Remover</button></div></li>').join(''):'<li class="muted">Sem combinações. Use a busca acima para adicionar.</li>';
    $('#combination-example-title',root).textContent=name(Number(source.value));
    $('#combination-preview',root).innerHTML=selected.filter(id=>products.find(p=>p.id===id)?.active).map(id=>'<div>'+esc(name(id))+'<span>Escolher →</span></div>').join('')||'<p>As sugestões gerais continuam disponíveis na sacola.</p>';
    $$('[data-combine]',root).forEach(b=>b.onclick=()=>{selected.push(Number(b.dataset.combine));changed();});
    $$('[data-remove]',root).forEach(b=>b.onclick=()=>{selected=selected.filter(id=>id!==Number(b.dataset.remove));changed();});
    $$('[data-move]',root).forEach(b=>b.onclick=()=>{const i=Number(b.dataset.move),j=i+Number(b.dataset.step);[selected[i],selected[j]]=[selected[j],selected[i]];changed();});
  }
  function changed(){dirty=true;status('Alterações ainda não salvas.');draw();}
  // Save a draft per source so changing the selector cannot silently discard work.
  const drafts=new Map();let previous='';
  source.onchange=()=>{
    if(previous&&dirty)drafts.set(Number(previous),[...selected]);
    previous=source.value;const product=products.find(p=>p.id===Number(source.value));
    $('#combination-editor',root).hidden=!product;
    if(!product)return;
    selected=[...(drafts.get(product.id)||product.suggestion_ids)];dirty=drafts.has(product.id);
    $('#combination-search',root).value='';status(dirty?'Alterações ainda não salvas.':'');draw();
  };
  $('#combination-search',root).oninput=draw;
  bindForm(form,async()=>{
    const pid=Number(source.value),ids=[...selected];source.disabled=true;form.inert=true;
    try{await api('/api/admin/marketing/combinations/'+pid,{method:'PUT',body:JSON.stringify({ids})});products.find(p=>p.id===pid).suggestion_ids=ids;drafts.delete(pid);dirty=false;status('Combinações salvas e disponíveis no cardápio.');toast('Combinações salvas.');}finally{source.disabled=false;form.inert=false;}
  });
  function report(r){
    const metric=(label,value)=>'<article class="metric"><div><small>'+label+'</small><strong>'+value+'</strong></div></article>';
    $('#combination-report',root).innerHTML='<div class="metrics three">'+metric('Pedidos com combinações',r.totals.orders)+metric('Itens sugeridos vendidos',r.totals.units)+metric('Valor bruto dos itens',money(r.totals.gross))+'</div>'+(r.ranking.length?'<p class="table-hint">Arraste para o lado para ver todas as colunas. Até 100 combinações por valor vendido.</p><div class="table-wrap" tabindex="0" aria-label="Vendas por combinação"><table><thead><tr><th>Produto principal</th><th>Produto sugerido</th><th>Pedidos</th><th>Unidades</th><th>Valor bruto</th></tr></thead><tbody>'+r.ranking.map(row=>'<tr><td>'+esc(row.source_name)+'</td><td>'+esc(row.name)+'</td><td>'+row.orders+'</td><td>'+row.units+'</td><td>'+money(row.gross)+'</td></tr>').join('')+'</tbody></table></div>':empty('Suas combinações começam aqui','Configure as sugestões acima. Quando um pedido com esses itens for concluído, os resultados aparecerão aqui.'));
  }
  report(initialReport);
  $('#combination-days',root).onchange=async e=>{
    const version=++loadingReport,days=e.target.value;
    $('#combination-report',root).innerHTML='<p role="status">Carregando resultados…</p>';
    try{const r=await api('/api/admin/marketing/combinations/report?days='+days);if(version===loadingReport&&root.isConnected)report(r);}catch(err){if(version===loadingReport)$('#combination-report',root).textContent=err.message;}
  };
}
