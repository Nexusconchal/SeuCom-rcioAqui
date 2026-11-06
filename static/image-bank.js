// Banco de imagens: fotos ilustrativas com licença livre para quem não tem foto do produto.
import { $, $$, esc, icon } from './ui.js';

const BASE = '/static/banco-imagens/';
const STOP = new Set(['de','da','do','das','dos','com','sem','e','a','o','as','os','na','no','ao','à','em','para','x']);
let catalog = null;

export const isBankImage = url => /^\/static\/banco-imagens\/[a-z0-9-]+\.webp$/.test(url || '');
const norm = value => String(value || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const words = value => norm(value).split(/[^a-z0-9]+/).filter(w => w.length > 1 && !STOP.has(w));

async function load(){
  if(catalog) return catalog;
  const response = await fetch(BASE + 'catalogo.json', {credentials:'same-origin'});
  if(!response.ok) throw new Error('Não foi possível abrir o banco de imagens.');
  catalog = await response.json();
  catalog.imagens.forEach(item => item.busca = ' ' + words(item.nome + ' ' + item.categoria + ' ' + item.tags).join(' ') + ' ');
  return catalog;
}

// Pontua pela quantidade de palavras encontradas; palavra inteira vale mais que pedaço.
function score(item, terms){
  let total = 0;
  for(const term of terms){
    if(item.busca.includes(' ' + term + ' ')) total += 3;
    else if(item.busca.includes(' ' + term)) total += 2;
    else if(term.length > 3 && item.busca.includes(term)) total += 1;
  }
  return total;
}

export function search(items, query, category = ''){
  const pool = category ? items.filter(item => item.categoria === category) : items;
  const terms = words(query);
  if(!terms.length) return pool;
  return pool.map(item => [score(item, terms), item]).filter(([value]) => value > 0)
    .sort((a, b) => b[0] - a[0] || a[1].nome.localeCompare(b[1].nome, 'pt-BR')).map(([, item]) => item);
}

export async function openImageBank(initial, onPick){
  const data = await load();
  let dialog = $('#image-bank');
  if(!dialog){
    dialog = document.createElement('dialog');
    dialog.id = 'image-bank';
    dialog.setAttribute('aria-labelledby', 'image-bank-title');
    document.body.append(dialog);
  }
  dialog.className = 'wide image-bank';
  let query = search(data.imagens, initial).length ? initial : '';
  let category = '';
  dialog.innerHTML = '<div class="dialog-head"><div><h2 id="image-bank-title">Banco de imagens</h2><p class="muted">Sem foto do produto? Escolha uma foto ilustrativa.</p></div><button class="icon-btn" type="button" data-bank-close aria-label="Fechar">'+icon('close')+'</button></div>'+
    '<label class="bank-search"><span class="sr-only">Buscar imagem</span><input type="search" placeholder="Buscar por nome ou sabor (ex.: calabresa)" value="'+esc(query)+'" autocomplete="off"></label>'+
    '<div class="chips bank-chips" role="group" aria-label="Categorias"></div><div class="bank-grid" aria-live="polite"></div>'+
    '<p class="bank-credits muted">Fotos ilustrativas com licença livre (Creative Commons). <a class="text-link" href="'+BASE+'creditos.html" target="_blank" rel="noopener">Autores e licenças</a></p>';
  const input = $('input', dialog), chips = $('.bank-chips', dialog), grid = $('.bank-grid', dialog);
  function draw(){
    const found = search(data.imagens, query);
    const count = name => found.filter(item => item.categoria === name).length;
    chips.innerHTML = ['', ...data.categorias].map(name => {
      const total = name ? count(name) : found.length;
      return total || name === category ? '<button type="button" class="chip '+(name === category ? 'active' : '')+'" data-bank-category="'+esc(name)+'" aria-pressed="'+(name === category)+'">'+esc(name || 'Todas')+' ('+total+')</button>' : '';
    }).join('');
    const list = category ? found.filter(item => item.categoria === category) : found;
    grid.innerHTML = list.length ? list.map(item => '<button type="button" class="bank-item" data-bank-id="'+esc(item.id)+'"><img src="'+BASE+esc(item.arquivo)+'" alt="" loading="lazy" width="300" height="300"><span>'+esc(item.nome)+'</span></button>').join('')
      : '<p class="muted bank-empty">Nenhuma imagem encontrada. Tente outra palavra ou envie a sua foto.</p>';
    $$('[data-bank-category]', chips).forEach(button => button.onclick = () => { category = button.dataset.bankCategory; draw(); });
    $$('[data-bank-id]', grid).forEach(button => button.onclick = () => {
      const item = data.imagens.find(entry => entry.id === button.dataset.bankId);
      dialog.close();
      onPick(BASE + item.arquivo, item);
    });
  }
  let timer;
  input.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { query = input.value; draw(); grid.scrollTop = 0; }, 120); };
  $('[data-bank-close]', dialog).onclick = () => dialog.close();
  dialog.onclick = event => { if(event.target === dialog) dialog.close(); };
  draw();
  dialog.showModal();
  input.focus();
}
