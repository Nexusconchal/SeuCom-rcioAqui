import { $, icon, brand, auth, bootstrap, api, bindForm, esc, toast } from './ui.js';

async function start(){
  try{
    await bootstrap();
    const path=location.pathname.split('/').filter(Boolean);
    if(path[0]==='rede')return await (await import('./network.js')).networkPage(path[1]||'');
    if(path[0]==='entregador')return await (await import('./delivery.js')).driverPage();
    if(path[0]==='loja')return await (await import('./menu.js')).renderMenu(decodeURIComponent(path[1]||''));
    if(path[0]==='pedido')return await (await import('./menu.js')).renderTracking(path[1]||'');
    if(path[0]==='admin'||path[0]==='plataforma')return await (await import('./management.js')).renderOwnerSite();
    if(path[0]==='painel')return auth.user?await (await import('./dashboard.js')).renderDashboard():location.replace('/entrar');
    if(path[0]==='entrar')return new URLSearchParams(location.search).has('recuperar')?(await import('./recovery.js')).recoveryPage():loginPage();
    if(path[0]==='termos'||path[0]==='privacidade')return legalPage(path[0]);
    return (await import('./landing.js')).renderLanding();
  }catch(error){
    $('#app').innerHTML='<main id="main" class="loading">'+brand()+'<h1>Não conseguimos abrir esta página</h1><p>'+esc(error.message)+'</p><a class="btn" href="/">Ir ao início</a><button id="retry" class="btn secondary">Tentar novamente</button></main>';
    $('#retry').onclick=()=>location.reload();
  }
}

const LEGAL={
 termos:['Termos de uso','<p><b>Última atualização:</b> outubro de 2026. Rascunho a ser revisado por um advogado antes do lançamento comercial.</p><h2>1. O que é o SeuComércioAqui</h2><p>Plataforma que permite a comércios (“lojistas”) publicar um cardápio digital, receber pedidos e organizar a operação. A venda é feita pelo lojista, que é o responsável pelos produtos, preços, entrega, atendimento, trocas e emissão de documentos fiscais.</p><h2>2. Conta do lojista</h2><p>O lojista cria a conta com dados verdadeiros, guarda a senha em segurança e responde pelo que for feito com o seu acesso e com os acessos da equipe que cadastrar.</p><h2>3. Planos, teste grátis e bloqueio</h2><p>Novas lojas podem ter um período de teste grátis. Depois, vale a mensalidade e/ou comissão combinadas. A plataforma pode suspender lojas com pagamento em atraso, uso indevido ou violação destes termos, mantendo o histórico.</p><h2>4. Pagamentos</h2><p>No Pix comum, o cliente paga direto ao lojista. No Pix automático, o pagamento é processado pela conta do lojista no Mercado Pago, sob as regras e taxas desse serviço. A plataforma não guarda dados de cartão.</p><h2>5. Uso permitido</h2><p>É proibido vender produtos ilegais, publicar conteúdo enganoso, tentar acessar dados de outras lojas ou prejudicar o funcionamento do sistema.</p><h2>6. Disponibilidade</h2><p>Trabalhamos para manter o serviço disponível, mas podem ocorrer interrupções para manutenção ou por falhas de terceiros.</p><h2>7. Contato</h2><p>suporte@seucomercioaqui.com.br</p>'],
 privacidade:['Política de privacidade','<p><b>Última atualização:</b> outubro de 2026. Rascunho a ser revisado por um advogado antes do lançamento comercial.</p><h2>Quem cuida dos seus dados</h2><p>Quando você faz um pedido, a <b>loja</b> é a controladora dos seus dados e o SeuComércioAqui atua como <b>operador</b>, guardando e processando as informações em nome dela (LGPD, Lei 13.709/2018).</p><h2>Quais dados</h2><p>Nome, WhatsApp, endereço de entrega, itens do pedido, forma de pagamento, avaliações e, se você permitir, os dados lembrados no seu próprio aparelho.</p><h2>Para quê</h2><p>Preparar e entregar o pedido, falar com você sobre ele, confirmar o pagamento, emitir relatórios para a loja e aplicar benefícios como cupons e fidelidade. Não vendemos seus dados.</p><h2>Promoções e lembretes</h2><p>Os lembretes de sacola e as ofertas pelo WhatsApp dependem de escolhas separadas e opcionais no checkout. Você pode cancelar pelo link da mensagem. O contato e os itens de uma sacola inacabada ficam disponíveis para recuperação por até 7 dias; as sessões anônimas do cardápio são mantidas por até 30 dias para medir visitas e pedidos. Nenhum contato é capturado para recuperação sem sua autorização.</p><h2>Com quem compartilhamos</h2><p>Com a loja do pedido, com o parceiro de entrega que a loja escolher e com o Mercado Pago quando você usa o Pix automático.</p><h2>Por quanto tempo</h2><p>Enquanto a loja precisar para a operação e para obrigações legais e contábeis.</p><h2>Seus direitos</h2><p>Você pode pedir acesso, correção ou exclusão dos seus dados diretamente à loja. A loja consegue apagar seus dados pessoais no painel, mantendo apenas os valores para a contabilidade.</p><h2>Segurança</h2><p>Conexão criptografada (HTTPS), senhas protegidas por hash, credenciais de pagamento criptografadas e acesso separado por loja e por função.</p><h2>Contato</h2><p>suporte@seucomercioaqui.com.br</p>']};
function legalPage(kind){
  const [title,body]=LEGAL[kind];document.title=title+' • SeuComércioAqui';
  $('#app').innerHTML='<header class="site-head">'+brand()+'<nav><a class="btn secondary" href="/">Início</a></nav></header><main id="main" class="legal"><h1>'+title+'</h1>'+body+'</main><footer>'+brand()+'<p><a href="/termos">Termos de uso</a> • <a href="/privacidade">Privacidade</a></p></footer>';
}
function loginPage(){
  const register=new URLSearchParams(location.search).has('cadastro')&&auth.registration;
  $('#app').innerHTML='<div class="auth-layout"><aside class="auth-art">'+brand()+'<div><span class="eyebrow">SEU NOVO BALCÃO DIGITAL</span><h1>O comércio<br>é seu.<br><em>O próximo passo<br>é aqui.</em></h1><p>Mais organização para você.<br>Mais facilidade para quem compra.</p></div><small>Seu negócio. Mais perto.</small></aside><main id="main" class="auth-main"><a class="text-link" href="/">← Voltar ao início</a><div class="auth-card"><span class="eyebrow">'+(register?'VAMOS COMEÇAR':'BOM TER VOCÊ POR AQUI')+'</span><h1>'+(register?'Crie sua loja':'Entre na sua conta')+'</h1><p class="muted">'+(register?'Seu cardápio começa com um nome.':'O seu comércio está a um passo.')+'</p><form id="auth-form">'+
    (register?'<label>Seu nome<input name="name" autocomplete="name" minlength="2" maxlength="100" required></label><label>Nome do comércio<input name="store_name" maxlength="100" minlength="2" required></label><label>Nome da sua loja no link<input name="slug" aria-label="Nome da sua loja no link" aria-describedby="slug-help slug-link-help" pattern="[a-z0-9]+" minlength="3" maxlength="60" placeholder="nomedasualoja" autocapitalize="none" autocomplete="off" spellcheck="false" title="Use de 3 a 60 letras ou números, tudo junto, sem espaços e sem acentos." required><small id="slug-help" style="font-size:12px;line-height:1.5">Escreva tudo junto, sem espaços e sem acentos. Exemplo: <b>nomedasualoja</b>.</small><small id="slug-link-help" style="overflow-wrap:anywhere;font-size:12px;line-height:1.5">Seus clientes verão este link para acessar o cardápio:<br><strong id="slug-preview"></strong></small></label>':'')+
    '<label>E-mail<input name="email" type="email" autocomplete="email" maxlength="254" required></label><label>Senha<input name="password" aria-label="Senha" type="password" autocomplete="'+(register?'new-password':'current-password')+'" minlength="'+(register?'10':'1')+'" maxlength="128" required>'+(register?'<small>Use ao menos 10 caracteres.</small>':'')+'</label>'+(register?'<label class="check-row terms"><span><input type="checkbox" name="accept_terms" required> Li e aceito os <a href="/termos" target="_blank">Termos de uso</a> e a <a href="/privacidade" target="_blank">Política de privacidade</a></span></label>':'')+'<p class="form-error" role="alert" hidden></p><button type="submit" class="btn full">'+(register?'Criar minha loja':'Entrar no painel')+icon('arrow')+'</button></form>'+
    (auth.registration?'<p class="auth-switch">'+(register?'Já tem uma conta? <a href="/entrar">Entrar</a>':'Ainda não tem uma loja? <a href="/entrar?cadastro=1">Criar conta</a>')+'</p>':'')+
    (!register?'<p class="help"><a href="/entrar?recuperar=1">Esqueci minha senha</a></p>':'')+'</div></main></div>';
  if(register){
    const slug=$('[name=slug]');
    const compactName=value=>value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]/g,'').slice(0,60);
    const preview=()=>{$('#slug-preview').textContent=location.origin+'/loja/'+(slug.value||'nomedasualoja');};
    $('[name=store_name]').addEventListener('input',e=>{if(!slug.dataset.manual)slug.value=compactName(e.target.value);preview();});
    slug.addEventListener('input',()=>{slug.dataset.manual='1';slug.value=compactName(slug.value);preview();});
    preview();
  }
  bindForm($('#auth-form'),async form=>{
    const result=await api('/api/auth/'+(register?'register':'login'),{method:'POST',body:JSON.stringify({...Object.fromEntries(form),...(register?{accept_terms:form.has('accept_terms')}:{})})});
    auth.user=result.user;location.href='/painel';
  });
}
window.addEventListener('hashchange',()=>{
  if(location.pathname==='/entrar'&&new URLSearchParams(location.search).has('recuperar')&&location.hash)
    import('./recovery.js').then(module=>module.recoveryPage());
});
start();
