import { $,api,esc,money,toast } from './ui.js';

export async function confirmWallet(slug,phone,root,done){
  const r=await api('/api/store/'+encodeURIComponent(slug)+'/wallet/code',{method:'POST',body:JSON.stringify({phone})});
  root.innerHTML='<p>Enviamos um código para '+esc(phone)+'. Ele vale por 5 minutos.</p><label>Código de 6 dígitos<input id="wallet-code" inputmode="numeric" autocomplete="one-time-code" minlength="6" maxlength="6"></label><button class="btn secondary" id="verify-wallet" type="button">Confirmar código</button><p id="wallet-error" class="form-error" role="alert"></p>';
  $('#verify-wallet',root).onclick=async()=>{const button=$('#verify-wallet',root);button.disabled=true;try{const verified=await api('/api/store/'+encodeURIComponent(slug)+'/wallet/verify',{method:'POST',body:JSON.stringify({challenge:r.challenge,code:$('#wallet-code',root).value})});done(verified);toast('Saldo disponível: '+money(verified.balance));}catch(e){$('#wallet-error',root).textContent=e.message;}finally{if(button.isConnected)button.disabled=false;}};
}
