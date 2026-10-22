import { $, api, auth, brand, bindForm, esc } from './ui.js';

export function recoveryPage(){
  const token=location.hash.slice(1);
  history.replaceState(null,'','/entrar?recuperar=1');
  document.title='Recuperar acesso • SeuComércioAqui';
  $('#app').innerHTML='<main id="main" class="recovery-page">'+brand()+'<section class="panel"><span class="eyebrow">SUA CONTA, EM SEGURANÇA</span><h1>'+(token?'Escolha uma nova senha':'Recupere seu acesso')+'</h1><p>'+(token?'Depois da troca, entre novamente em todos os seus aparelhos.':'Informe o e-mail usado para criar sua conta. O link vale por 30 minutos.')+'</p><div id="recovery-content">'+(!token&&!auth.recovery_available?'<div class="notice"><b>Envio de e-mail ainda não ativado</b><p>Entre em contato com o suporte ou com o administrador da plataforma para recuperar o acesso.</p></div>':'<form id="recovery-form">'+(token?'<label>Nova senha<input type="password" name="password" aria-label="Nova senha" autocomplete="new-password" minlength="10" maxlength="128" required><small>Use ao menos 10 caracteres.</small></label><label>Confirme a nova senha<input type="password" name="confirmation" autocomplete="new-password" minlength="10" maxlength="128" required></label>':'<label>E-mail da sua conta<input type="email" name="email" autocomplete="email" maxlength="254" required></label>')+'<p class="form-error" role="alert" hidden></p><button class="btn full" type="submit">'+(token?'Salvar nova senha':'Enviar link de recuperação')+'</button></form>')+'</div><p><a class="text-link" href="/entrar">Voltar para entrar</a></p></section></main>';
  const form=$('#recovery-form');if(!form)return;
  bindForm(form,async fields=>{
    if(token&&fields.get('password')!==fields.get('confirmation'))throw Error('As senhas precisam ser iguais.');
    const result=await api('/api/auth/recovery'+(token?'/complete':''),{method:'POST',body:JSON.stringify(token?{token,password:fields.get('password')}:{email:fields.get('email')})});
    $('#recovery-content').innerHTML='<div class="notice" role="status"><b>'+(token?'Senha alterada.':esc(result.message))+'</b><p>'+(token?'As sessões antigas foram encerradas. Entre com sua nova senha.':'Se não receber a mensagem em alguns minutos, confira o spam e tente novamente.')+'</p></div>';
  });
}
