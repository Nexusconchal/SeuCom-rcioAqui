import { $, $$, esc, date, toast } from './ui.js';

// Only IDs and operator confirmations are persisted. Customer data and ticket
// HTML are fetched with authorization when reprinting, never cached here.
let scope='', view=null, reprint=null, historyPage=0;
const states={pending:'Pendente',printing:'Envio interrompido ou em andamento — confira',awaiting:'Confira se saiu no papel',error:'Falha ao abrir impressão',confirmed:'Conferido pela equipe',skipped:'Dispensado pela equipe'};
function read(){
  if(!scope)throw Error('A loja ainda não foi identificada para imprimir.');
  const raw=localStorage.getItem(scope);if(!raw)return {version:1,jobs:[]};
  const value=JSON.parse(raw);
  if(value.version!==1||!Array.isArray(value.jobs)||value.jobs.length>500||value.jobs.some(j=>!Number.isSafeInteger(j.order_id)||j.order_id<1||!Object.hasOwn(states,j.state)||typeof j.key!=='string'||typeof j.what!=='string'||j.what.length>100))throw Error('Histórico de impressão inválido. Confira o armazenamento deste navegador com o suporte.');
  return value;
}
function save(value){
  const cutoff=Date.now()-30*86400000;
  const pending=value.jobs.filter(j=>!['confirmed','skipped'].includes(j.state));
  const completed=value.jobs.filter(j=>['confirmed','skipped'].includes(j.state)&&Date.parse(j.updated_at)>=cutoff);
  if(pending.length>500)throw Error('Há muitas pendências de impressão. Confira o histórico antes de continuar.');
  const keep=500-pending.length;
  value.jobs=[...pending,...(keep?completed.slice(-keep):[])].sort((a,b)=>Date.parse(a.updated_at)-Date.parse(b.updated_at));
  localStorage.setItem(scope,JSON.stringify(value));
  window.dispatchEvent(new Event('sca:print-journal'));
}
export function initPrintJournal(storeId,userId){scope='sca.print-journal.'+storeId+'.'+userId;historyPage=0;}
export function enqueuePrint(order,what='all'){
  const value=read(),key=order.id+':'+what;
  let job=value.jobs.find(j=>j.key===key);
  if(!job){job={key,order_id:order.id,number:order.number,what,state:'pending',attempts:0,updated_at:new Date().toISOString()};value.jobs.push(job);save(value);}
  return job;
}
export function pendingPrints(){return read().jobs.filter(j=>!['confirmed','skipped'].includes(j.state));}
function change(key,state){const value=read(),job=value.jobs.find(j=>j.key===key);if(!job)throw Error('Impressão não encontrada.');job.state=state;job.updated_at=new Date().toISOString();if(state==='printing')job.attempts++;save(value);}
export async function trackedPrint(order,what,action,automatic=false){
  let job;
  try{job=enqueuePrint(order,what);}catch{toast('Não foi possível guardar a pendência. Confira o armazenamento do navegador antes de imprimir.');return;}
  const run=async()=>{
    const current=read().jobs.find(j=>j.key===job.key);
    if(automatic&&current.state!=='pending')return;
    change(job.key,'printing');
    try{const result=await action();change(job.key,result?.error?'error':'awaiting');}
    catch{change(job.key,'error');toast('Confira a impressora e tente novamente no histórico.');}
  };
  // Modern Chrome/Edge coordinate tabs of this browser. Never silently run
  // automatic jobs without the lock that prevents duplicate dispatches.
  try{
    if(navigator.locks)await navigator.locks.request(scope+':'+job.key,run);
    else if(automatic)toast('Use Chrome ou Edge atualizado para imprimir automaticamente com controle de duplicidade.');
    else await run();
  }catch{toast('Não consegui atualizar o histórico de impressão. Confira o papel antes de repetir.');}
}
function draw(){
  if(!view?.isConnected)return;
  try{
    const jobs=read().jobs.slice().reverse().sort((a,b)=>Number(['confirmed','skipped'].includes(a.state))-Number(['confirmed','skipped'].includes(b.state)));
    const pages=Math.max(1,Math.ceil(jobs.length/100));historyPage=Math.min(historyPage,pages-1);
    view.innerHTML='<div class="section-heading"><div><span class="eyebrow">NESTE NAVEGADOR E NESTE ACESSO</span><h2>Pendências e histórico de impressão</h2><p class="muted">Fechar a janela de impressão não confirma que saiu papel. Confira antes de repetir.</p></div></div>'+(jobs.length?'<div class="table-wrap"><table><thead><tr><th>Pedido / via</th><th>Situação</th><th>Última ação</th><th>Ações</th></tr></thead><tbody>'+jobs.slice(historyPage*100,(historyPage+1)*100).map(j=>'<tr><td><b>#'+esc(j.number)+'</b><br><small>'+esc(j.what==='all'?'Notinha completa':j.what==='driver'?'Via do motoboy':j.what.slice(7)||'Produção')+'</small></td><td>'+esc(states[j.state])+'<br><small>'+esc(j.attempts)+' tentativa(s)</small></td><td>'+date(j.updated_at)+'</td><td><div class="row-actions"><button class="btn secondary small" data-journal-print="'+esc(j.key)+'">'+(j.attempts?'Reimprimir':'Imprimir')+'</button>'+(!['confirmed','skipped'].includes(j.state)?'<button class="btn secondary small" data-journal-confirm="'+esc(j.key)+'">Conferi no papel</button><button class="text-link" data-journal-skip="'+esc(j.key)+'">Dispensar</button>':'')+'</div></td></tr>').join('')+'</tbody></table></div><p class="muted">Até 100 registros exibidos; '+pendingPrints().length+' pendência(s) no histórico. Registros conferidos são mantidos por até 30 dias.</p><div class="row-actions"><button class="btn secondary small" id="print-history-previous" '+(!historyPage?'disabled':'')+'>Anterior</button><span>Página '+(historyPage+1)+' de '+pages+'</span><button class="btn secondary small" id="print-history-next" '+(historyPage+1>=pages?'disabled':'')+'>Próxima</button></div>':'<p class="muted">As impressões de pedidos aparecerão aqui. O teste da impressora não cria pedidos.</p>');
    if($('#print-history-previous',view))$('#print-history-previous',view).onclick=()=>{historyPage--;draw();};
    if($('#print-history-next',view))$('#print-history-next',view).onclick=()=>{historyPage++;draw();};
    $$('[data-journal-print]',view).forEach(b=>b.onclick=async()=>{b.disabled=true;try{const job=read().jobs.find(j=>j.key===b.dataset.journalPrint);await reprint(job);}catch(e){toast(e.message);}finally{if(b.isConnected)b.disabled=false;}});
    $$('[data-journal-confirm]',view).forEach(b=>b.onclick=()=>{try{change(b.dataset.journalConfirm,'confirmed');}catch{toast('Não consegui salvar a conferência.');}});
    $$('[data-journal-skip]',view).forEach(b=>b.onclick=()=>{try{change(b.dataset.journalSkip,'skipped');}catch{toast('Não consegui salvar a alteração.');}});
  }catch{view.innerHTML='<p class="notice">Não foi possível ler o histórico. Libere o armazenamento deste navegador para controlar as pendências.</p>';}
}
export function mountPrintJournal(root,handler){view=root;reprint=handler;draw();}
window.addEventListener('sca:print-journal',draw);
window.addEventListener('storage',e=>{if(e.key===scope)draw();});
