import { renderOwnerSite } from './management.js';
import { $, icon, brand, auth, bootstrap, api, bindForm, esc, toast, attachFallbacks } from './ui.js';
import { renderMenu, renderTracking } from './menu.js';
import { renderDashboard } from './dashboard.js';

async function start(){
  try{
    await bootstrap();
    const path=location.pathname.split('/').filter(Boolean);
    if(path[0]==='loja')return await renderMenu(decodeURIComponent(path[1]||''));
    if(path[0]==='pedido')return await renderTracking(path[1]||'');
    if(path[0]==='admin'||path[0]==='plataforma')return await renderOwnerSite();
    if(path[0]==='painel')return auth.user?await renderDashboard():location.replace('/entrar');
    if(path[0]==='entrar')return loginPage();
    landing();
  }catch(error){
    $('#app').innerHTML='<main id="main" class="loading">'+brand()+'<h1>Não conseguimos abrir esta página</h1><p>'+esc(error.message)+'</p><a class="btn" href="/">Ir ao início</a><button id="retry" class="btn secondary">Tentar novamente</button></main>';
    $('#retry').onclick=()=>location.reload();
  }
}
function landing(){
  $('#app').innerHTML='<header class="site-head">'+brand()+'<nav><a href="#como-funciona">Como funciona</a><a class="btn secondary" href="'+(auth.user?'/painel':'/entrar')+'">'+(auth.user?'Meu painel':'Entrar')+'</a></nav></header>'+
  '<main id="main"><section class="hero"><div class="hero-copy"><span class="eyebrow"><i></i> O seu comércio, conectado.</span><h1>Seu negócio.<br>Mais perto.<br><em>Mais pedidos.</em></h1><p>Um cardápio que dá vontade de pedir.<br>Um painel que deixa seu dia mais leve.</p><a class="btn lime large" href="'+(auth.user?'/painel':'/entrar?cadastro=1')+'">'+(auth.user?'Abrir meu painel':'Criar minha loja')+icon('arrow')+'</a><div class="hero-proof"><span>'+icon('check')+' Sem app para instalar</span><span>'+icon('check')+' Sua própria marca</span></div></div>'+
  '<div class="hero-visual"><div class="floating-label">'+icon('bell')+' Mais simples, do pedido à entrega</div><div class="phone-preview"><div class="notch"></div><img class="preview-cover" alt="Hambúrguer artesanal" src="https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=900&auto=format&fit=crop&q=85"><div class="preview-store"><b>Bistrô da Vila</b><span class="badge green">Aberto</span><small>por SeuComércioAqui</small></div><div class="preview-content"><div class="fake-search">'+icon('search')+' O que você quer pedir?</div><div class="chips"><span class="chip active">Destaques</span><span class="chip">Lanches</span><span class="chip">Bebidas</span></div><div class="preview-product"><img src="https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=250&auto=format&fit=crop&q=80" alt=""><div><b>Burger da casa</b><small>Feito com carinho, do seu jeito.</small><strong>R$ 29,00</strong></div><span class="plus-circle">+</span></div><div class="preview-cart">'+icon('bag')+' Seu próximo pedido está aqui '+icon('arrow')+'</div></div></div><div class="floating-card">'+icon('chart')+'<div><b>Seu comércio em movimento</b><small>Cardápio, pedidos e vendas em um lugar.</small></div></div></div></section>'+
  '<section class="feature-section" id="como-funciona"><span class="eyebrow">MENOS COMPLICAÇÃO. MAIS COMÉRCIO.</span><h2>Do link ao pedido,<br>tudo no seu ritmo.</h2><div class="features">'+
  [['store','Um cardápio com a sua cara','Fotos, categorias, complementos e promoções. Compartilhe o link da loja com seus clientes.'],['bag','Pedidos bem organizados','Receba pedidos, acompanhe o preparo e organize as entregas em um painel simples.'],['chart','Você sabe como foi o dia','Vendas, recebimentos e despesas. Os números que ajudam você a cuidar do seu negócio.']].map(([i,t,d])=>'<article><span class="feature-icon">'+icon(i)+'</span><h3>'+t+'</h3><p>'+d+'</p></article>').join('')+'</div></section>'+
  '<section class="landing-cta"><img src="/static/logo.svg" alt="" width="60"><div><h2>Seu comércio cabe aqui.</h2><p>Abra sua loja digital e dê o próximo passo.</p></div><a class="btn lime" href="/entrar?cadastro=1">Começar agora '+icon('arrow')+'</a></section></main><footer>'+brand()+'<p>Feito para quem faz o comércio acontecer.</p></footer>';
  attachFallbacks();
}
function loginPage(){
  const register=new URLSearchParams(location.search).has('cadastro')&&auth.registration;
  $('#app').innerHTML='<div class="auth-layout"><aside class="auth-art">'+brand()+'<div><span class="eyebrow">SEU NOVO BALCÃO DIGITAL</span><h1>O comércio<br>é seu.<br><em>O próximo passo<br>é aqui.</em></h1><p>Mais organização para você.<br>Mais facilidade para quem compra.</p></div><small>Seu negócio. Mais perto.</small></aside><main id="main" class="auth-main"><a class="text-link" href="/">← Voltar ao início</a><div class="auth-card"><span class="eyebrow">'+(register?'VAMOS COMEÇAR':'BOM TER VOCÊ POR AQUI')+'</span><h1>'+(register?'Crie sua loja':'Entre na sua conta')+'</h1><p class="muted">'+(register?'Seu cardápio começa com um nome.':'O seu comércio está a um passo.')+'</p><form id="auth-form">'+
    (register?'<label>Seu nome<input name="name" autocomplete="name" minlength="2" maxlength="100" required></label><label>Nome do comércio<input name="store_name" maxlength="100" minlength="2" required></label><label>Endereço da loja<input name="slug" pattern="[a-z0-9]+(-[a-z0-9]+)*" minlength="3" maxlength="60" placeholder="minha-loja" required><small>Seu link: /loja/<span id="slug-preview">minha-loja</span></small></label>':'')+
    '<label>E-mail<input name="email" type="email" autocomplete="email" maxlength="254" required></label><label>Senha<input name="password" aria-label="Senha" type="password" autocomplete="'+(register?'new-password':'current-password')+'" minlength="'+(register?'10':'1')+'" maxlength="128" required>'+(register?'<small>Use ao menos 10 caracteres.</small>':'')+'</label><p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">'+(register?'Criar minha loja':'Entrar no painel')+icon('arrow')+'</button></form>'+
    (auth.registration?'<p class="auth-switch">'+(register?'Já tem uma conta? <a href="/entrar">Entrar</a>':'Ainda não tem uma loja? <a href="/entrar?cadastro=1">Criar conta</a>')+'</p>':'')+
    (!register?'<details class="help"><summary>Esqueci minha senha</summary><p>A recuperação é feita pelo administrador da instalação. Entre em contato com quem hospeda a plataforma para redefinir sua senha.</p></details>':'')+'</div></main></div>';
  if(register){
    $('[name=store_name]').addEventListener('input',e=>{const slug=$('[name=slug]');if(!slug.dataset.manual)slug.value=e.target.value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');$('#slug-preview').textContent=slug.value||'minha-loja';});
    $('[name=slug]').addEventListener('input',e=>{e.target.dataset.manual='1';$('#slug-preview').textContent=e.target.value;});
  }
  bindForm($('#auth-form'),async form=>{
    const result=await api('/api/auth/'+(register?'register':'login'),{method:'POST',body:JSON.stringify(Object.fromEntries(form))});
    auth.user=result.user;location.href='/painel';
  });
}
start();
