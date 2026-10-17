import { $, icon, brand, auth, attachFallbacks, money } from './ui.js';

const burger='/static/landing-burger.webp';
const play='<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="currentColor"><path d="m8 5 12 7-12 7Z"/></svg>';
const chef='<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7 15a5 5 0 0 1-1-10 6 6 0 0 1 12 0 5 5 0 0 1-1 10v6H7v-6Zm0 3h10"/></svg>';
const table='<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 4v7a3 3 0 0 0 6 0V4M7 4v17M19 21V4c-4 3-4 9 0 9"/></svg>';

function orderCard(number,items,total,state){
  return `<div class="lp-mini-card"><div><b>#${number}</b><strong>${total}</strong></div><small>Delivery · 12:30</small><p>${items}</p><span class="lp-mini-state ${state}">${state==='new'?'Pedido recebido':state==='preparing'?'Em preparo':'Pronto para sair'}</span></div>`;
}

function productPreview(){
  return `<div class="lp-product" role="img" aria-label="Exemplo demonstrativo: cardápio no celular e painel com pedidos novos, em preparo e prontos">
    <div class="lp-product-backdrop"></div>
    <div class="lp-desktop"><div class="lp-window-head"><img src="/static/logo.svg" alt="" width="21" height="25"><b>SeuComércio<span>Aqui</span></b><span class="lp-window-store">Bistrô da Vila</span></div>
      <div class="lp-desktop-layout"><div class="lp-sidebar"><span class="active">${icon('bag')} Pedidos</span><span>${icon('store')} Cardápio</span><span>${table} Mesas</span><span>${icon('chart')} Vendas</span><span>${icon('gear')} Ajustes</span><small>Seu dia mais leve.</small></div>
      <div class="lp-board"><div class="lp-board-title"><b>Pedidos</b><span>Hoje ${icon('clock')}</span></div><div class="lp-lanes">
      <div class="lp-lane"><h3>Novos <span>2</span></h3>${orderCard('1024','1× Burger da casa<br>1× Batata rústica','R$ 47,00','new')}${orderCard('1025','1× Cheeseburger<br>1× Refrigerante','R$ 32,00','new')}</div>
      <div class="lp-lane preparing"><h3>Em preparo <span>2</span></h3>${orderCard('1023','1× Burger da casa<br>2× Refrigerante','R$ 45,00','preparing')}${orderCard('1021','2× Burger da casa','R$ 58,00','preparing')}</div>
      <div class="lp-lane ready"><h3>Prontos <span>1</span></h3>${orderCard('1020','1× Cheeseburger','R$ 24,00','ready')}</div></div></div></div></div>
    <div class="lp-phone"><div class="lp-phone-camera"></div><img class="lp-phone-cover" src="${burger}" alt="" width="210" height="158" fetchpriority="high"><div class="lp-phone-name"><b>Bistrô da Vila</b><span>Aberto</span><small>Sabor que aproxima.</small></div><div class="lp-phone-body"><div class="lp-phone-categories"><span>Destaques</span><span>Lanches</span><span>Bebidas</span></div><div class="lp-phone-item"><img src="${burger}" alt="" width="55" height="65"><div><b>Burger da casa</b><small>Pão brioche, queijo e molho da casa.</small><strong>R$ 29,00</strong></div><span>+</span></div><div class="lp-phone-cart">${icon('bag')} Seu próximo pedido está aqui</div></div></div>
    <div class="lp-received"><span>${icon('check')}</span><div><b>Pedido recebido</b><small>Do cardápio direto para a operação.</small></div></div><small class="lp-example">Exemplo demonstrativo</small>
  </div>`;
}

export function renderLanding(){
  const destination=auth.user?'/painel':auth.registration?'/entrar?cadastro=1':'/entrar';
  const cta=auth.user?'Abrir meu painel':auth.registration?'Criar meu cardápio':'Entrar na sua conta';
  const access=auth.user?'Meu painel':'Entrar';
  const start=auth.user?'Meu painel':auth.registration?'Começar agora':'Entrar';
  document.title='SeuComércioAqui • Cardápio digital e gestão para restaurantes';
  $('#app').innerHTML=`<div class="landing-page"><header class="lp-header">${brand()}<nav aria-label="Navegação principal"><a class="lp-nav-section" href="#recursos">Recursos</a><a class="lp-nav-section" href="#como-funciona">Como funciona</a><a class="lp-access" href="${auth.user?'/painel':'/entrar'}">${access}</a><a class="btn lime" href="${destination}">${start} ${icon('arrow')}</a></nav></header>
    <main id="main"><section class="lp-hero"><div class="lp-hero-copy"><p class="lp-kicker">CARDÁPIO DIGITAL E GESTÃO PARA RESTAURANTES</p><h1>Mais pedidos.<br>Menos correria.<em>Tudo no seu controle.</em></h1><p class="lp-lead">Receba pedidos, organize a cozinha e acompanhe suas vendas em um só lugar.</p><div class="lp-actions"><a class="btn lime large" href="${destination}">${cta} ${icon('arrow')}</a><a class="btn secondary large" href="#demonstracao">${play} Ver demonstração</a></div><div class="lp-proof"><span>${icon('check')} Sem app para instalar</span><span>${icon('check')} Com a sua marca</span></div></div>${productPreview()}</section>
    <div class="lp-channels" aria-label="Para toda a operação">${[['truck','Delivery'],['store','Balcão'],['table','Mesas'],['chef','Cozinha'],['wallet','Caixa']].map(([i,t])=>`<div>${i==='chef'?chef:i==='table'?table:icon(i)}<span>${t}</span></div>`).join('')}</div>
    <section class="lp-section lp-resources" id="recursos"><div class="lp-section-heading"><p class="lp-kicker">SEU NEGÓCIO, CONECTADO</p><h2>Da primeira escolha<br class="lp-mobile-break"> ao próximo pedido.</h2><p>Uma experiência boa para quem compra. Mais organização para quem faz acontecer.</p></div><div class="lp-feature-grid">${[
      [icon('store'),'Cardápio com sua marca','Fotos, categorias, complementos e combinações para o cliente escolher do seu jeito.','O cliente escolhe'],
      [chef,'Pedidos e cozinha','Acompanhe os pedidos, organize o preparo e mantenha sua equipe na mesma página.','Sua equipe prepara'],
      [icon('user'),'Clientes que voltam','Cupons, fidelidade e histórico de clientes para cuidar de quem já compra com você.','O relacionamento continua']
    ].map(([i,t,d,s])=>`<article><span class="lp-feature-icon">${i}</span><small>${s}</small><h3>${t}</h3><p>${d}</p></article>`).join('')}</div></section>
    <section class="lp-demo-section" id="demonstracao"><div class="lp-demo-copy"><p class="lp-kicker">VEJA ACONTECER</p><h2>Um pedido.<br> Todo mundo<br> na mesma página.</h2><p>Experimente o caminho do cardápio à cozinha nesta demonstração interativa.</p><div class="lp-demo-note">${icon('eye')} <span>É só uma simulação. Não cria pedidos nem movimenta o caixa.</span></div><a class="text-link" href="${destination}">${cta} ${icon('arrow')}</a></div><div class="lp-demo" aria-label="Demonstração interativa"><div class="lp-demo-head"><span class="badge green">Demonstração</span><span>Cardápio → Pedido → Cozinha</span></div><div class="lp-demo-steps" aria-label="Etapas do pedido"><span data-step="0" class="current">1. Escolher</span><span data-step="1">2. Preparar</span><span data-step="2">3. Pronto</span></div><div id="lp-demo-content" aria-live="polite" aria-atomic="true"></div><button class="text-link lp-reset" type="button" id="lp-demo-reset" hidden>Recomeçar demonstração ${icon('back')}</button></div></section>
    <section class="lp-section lp-how" id="como-funciona"><div class="lp-section-heading"><p class="lp-kicker">SIMPLES PARA COMEÇAR</p><h2>Sua loja digital em três passos.</h2></div><ol class="lp-how-grid"><li><span>01</span><h3>Dê a sua cara ao cardápio</h3><p>Cadastre os produtos, escolha as fotos e personalize a identidade da sua loja.</p></li><li><span>02</span><h3>Compartilhe seu link</h3><p>Coloque o cardápio no WhatsApp, nas redes sociais ou no QR Code das mesas.</p></li><li><span>03</span><h3>Cuide da operação</h3><p>Receba os pedidos e acompanhe preparo, entregas, caixa e relatórios no painel.</p></li></ol></section>
    <section class="lp-faq lp-section"><div><p class="lp-kicker">ANTES DE COMEÇAR</p><h2>O que você<br>quer saber?</h2></div><div>${[
      ['Preciso instalar algum aplicativo?','O cardápio e o painel funcionam pelo navegador. Você pode acessar pelo computador ou pelo celular.'],
      ['Posso usar minha marca?','Sim. Sua loja tem nome, identidade e um link próprio para compartilhar com os clientes.'],
      ['O sistema também serve para balcão e mesas?','Sim. Além do cardápio para delivery, o painel tem pedidos de balcão, mesas, comandas e acompanhamento da cozinha.'],
      ['Como conheço as condições do meu plano?','Ao criar sua conta, consulte a área Seu plano no painel. Ela mostra as condições disponíveis para sua loja antes de você confirmar uma assinatura.']
    ].map(([q,a])=>`<details><summary>${q}${icon('plus')}</summary><p>${a}</p></details>`).join('')}</div></section>
    <section class="lp-final"><div><p class="lp-kicker">SEU NEGÓCIO. MAIS PERTO.</p><h2>O próximo pedido<br>pode começar aqui.</h2><p>Seu cardápio, sua equipe e seus clientes mais conectados.</p></div><a class="btn lime large" href="${destination}">${cta} ${icon('arrow')}</a></section></main>
    <footer class="lp-footer">${brand()}<p>Feito para quem faz o comércio acontecer.</p><div><a href="/termos">Termos de uso</a><a href="/privacidade">Privacidade</a></div></footer></div>`;
  attachFallbacks();
  installDemo();
}

function installDemo(){
  let stage=0,quantity=0;
  const content=$('#lp-demo-content');
  function draw(){
    $('[data-step="0"]').classList.toggle('current',stage===0);
    $('[data-step="1"]').classList.toggle('current',stage===1);
    $('[data-step="2"]').classList.toggle('current',stage===2);
    $('#lp-demo-reset').hidden=stage===0&&quantity===0;
    if(stage===0){
      content.innerHTML=`<div class="lp-demo-product"><img src="${burger}" alt="Burger da casa" width="140" height="140" loading="lazy"><div><small>BISTRÔ DA VILA · EXEMPLO</small><h3>Burger da casa</h3><p>Pão brioche, carne, queijo e molho da casa.</p><strong>${money(2900)}</strong></div></div><div class="lp-demo-quantity"><span>Quantidade</span><div><button type="button" class="icon-btn" id="lp-demo-minus" aria-label="Remover um burger" ${quantity?'':'disabled'}>${icon('minus')}</button><output aria-label="Quantidade de burgers">${quantity}</output><button type="button" class="icon-btn" id="lp-demo-plus" aria-label="Adicionar um burger" ${quantity>=5?'disabled':''}>${icon('plus')}</button></div></div><button class="btn full" type="button" id="lp-demo-order" ${quantity?'':'disabled'}>Enviar pedido de exemplo ${quantity?'· '+money(quantity*2900):''} ${icon('arrow')}</button>`;
      $('#lp-demo-plus').onclick=()=>{quantity=Math.min(5,quantity+1);draw();$('#lp-demo-plus').focus();};
      $('#lp-demo-minus').onclick=()=>{quantity=Math.max(0,quantity-1);draw();(quantity?$('#lp-demo-minus'):$('#lp-demo-plus')).focus();};
      $('#lp-demo-order').onclick=()=>{stage=1;draw();$('#lp-demo-ready').focus();};
    }else{
      content.innerHTML=`<div class="lp-demo-result"><span class="lp-demo-result-icon">${stage===1?chef:icon('check')}</span><small>PEDIDO DE EXEMPLO #1024</small><h3>${stage===1?'Já está na cozinha.':'Pronto para o próximo passo.'}</h3><p>${quantity}× Burger da casa · ${money(quantity*2900)}</p><p>${stage===1?'A equipe acompanha os itens e avança o preparo pelo painel.':'No sistema, você acompanha a retirada ou a entrega e mantém o pedido organizado.'}</p></div>${stage===1?`<button class="btn full" type="button" id="lp-demo-ready">Marcar exemplo como pronto ${icon('check')}</button>`:'<div class="lp-demo-complete">'+icon('check')+' Simulação concluída. Nenhum pedido foi criado.</div>'}`;
      if(stage===1)$('#lp-demo-ready').onclick=()=>{stage=2;draw();$('#lp-demo-reset').focus();};
    }
    attachFallbacks(content);
  }
  $('#lp-demo-reset').onclick=()=>{stage=0;quantity=0;draw();$('#lp-demo-plus').focus();};
  draw();
}
