import { $, $$, icon, esc, modal, closeModal, empty } from './ui.js';
import { matchesSearch } from './search.js';

let activeHandler;
export function bindQuickNavigation(navigate,scope){
  const head=$('.head-actions');
  const recentKey='sca.navigation.'+scope;
  const readRecents=()=>{try{const value=JSON.parse(localStorage.getItem(recentKey));return Array.isArray(value)?value.filter(x=>typeof x==='string').slice(0,8):[];}catch{return [];}};
  const visit=id=>{try{localStorage.setItem(recentKey,JSON.stringify([id,...readRecents().filter(x=>x!==id)].slice(0,8)));}catch{}closeModal();navigate(id);};
  head.insertAdjacentHTML('afterbegin','<button id="quick-navigation" class="icon-btn" aria-label="Buscar no painel (Ctrl+K)" title="Buscar no painel (Ctrl+K)">'+icon('search')+'</button>');
  function open(){
    if($('#modal').open)return;
    // Read only the navigation already permitted for this team member.
    const pages=$$('.dashboard-nav [data-tab]').map(b=>({id:b.dataset.tab,label:b.textContent.replace(/\d+$/,'').trim()}));
    const d=modal('Buscar no painel','<label>Ir para uma página<input type="search" id="quick-query" placeholder="Ex.: relatório, caixa, impressão" autocomplete="off" maxlength="100" aria-controls="quick-results"></label><p class="muted">↑ ↓ para escolher • Enter para abrir • Esc para fechar</p><div id="quick-results" class="quick-results"></div>');
    let selected=0,results=[];
    function select(){const buttons=$$('[data-quick]',d);buttons.forEach((b,i)=>{b.classList.toggle('active',i===selected);b.setAttribute('aria-pressed',String(i===selected));});buttons[selected]?.scrollIntoView({block:'nearest'});}
    function draw(){const query=$('#quick-query').value,recents=readRecents();results=pages.filter(p=>matchesSearch(query,[p.label,p.id==='printing'?'impressora impressão cupom nota':p.id==='fiscal'?'nota fiscal nfce nfe documentos':p.id==='marketing'?'automação campanhas recompra recuperação sacolas':p.id==='reports'?'relatório exportar PDF Excel':'']));if(!query.trim())results.sort((a,b)=>(recents.indexOf(a.id)<0?99:recents.indexOf(a.id))-(recents.indexOf(b.id)<0?99:recents.indexOf(b.id)));selected=0;$('#quick-results').innerHTML=results.length?results.map(p=>'<button type="button" class="btn secondary quick-result" data-quick="'+p.id+'"><span>'+esc(p.label)+(!query.trim()&&recents.includes(p.id)?' <small class="muted">Recente</small>':'')+'</span>'+icon('arrow')+'</button>').join(''):empty('Nenhuma página encontrada','Tente outra palavra.');$$('[data-quick]',d).forEach(b=>b.onclick=()=>visit(b.dataset.quick));select();}
    $('#quick-query').oninput=draw;
    $('#quick-query').onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();closeModal();return;}if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();if(results.length)selected=(selected+(e.key==='ArrowDown'?1:-1)+results.length)%results.length;select();}else if(e.key==='Enter'){e.preventDefault();if(results[selected])visit(results[selected].id);}};
    draw();$('#quick-query').focus();
  }
  $('#quick-navigation').onclick=open;
  if(activeHandler)document.removeEventListener('keydown',activeHandler);
  activeHandler=e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();open();}};
  document.addEventListener('keydown',activeHandler);
}
