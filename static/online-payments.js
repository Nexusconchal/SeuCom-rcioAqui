import { $, api, esc, money, date, copy, toast, modal, closeModal } from './ui.js';

export const onlineMethod=o=>['pix_online','card_online'].includes(o.payment);
const labels={not_started:'Pagamento ainda não iniciado',creating:'Preparando pagamento',pending:'Aguardando pagamento',approved:'Pagamento confirmado',rejected:'Pagamento recusado',cancelled:'Cobrança cancelada',expired:'Prazo de pagamento encerrado',refunded:'Pagamento estornado',charged_back:'Pagamento contestado',uncertain:'Conferindo com o Mercado Pago',review:'Pagamento precisa de conferência'};
export function paymentLabel(p){return labels[p?.status]||'Conferir pagamento';}
function checkoutUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&['www.mercadopago.com.br','mercadopago.com.br','sandbox.mercadopago.com.br'].includes(u.hostname)&&(!u.port||u.port==='443')&&u.pathname.startsWith('/checkout/')?u.href:'';}catch{return '';}}

export function trackingPayment(o,token){
  const p=o.online_payment;if(!onlineMethod(o)||!p)return '';
  const pix=o.payment==='pix_online',active=!p.paid&&o.status!=='cancelled'&&!p.review;
  return '<section class="panel online-payment '+(p.review?'payment-review':'')+'" aria-labelledby="online-payment-title"><span class="eyebrow">PAGAMENTO DO PEDIDO</span><h2 id="online-payment-title">'+esc(p.status==='pending'?(pix?'Pague com Pix':'Pague com cartão'):paymentLabel(p))+'</h2><p>'+money(o.total)+' • '+(pix?'Pix com confirmação automática':'Cartão online pelo Mercado Pago')+'</p>'+
    (p.review?'<div class="notice">Fale com a loja antes de pagar novamente. Há um pagamento que precisa ser conferido.</div>':'')+
    (p.status==='approved'?'<p>O Mercado Pago confirmou o pagamento. Acompanhe o atendimento nesta página.</p>':'')+
    (['refunded','charged_back'].includes(p.status)?'<p>Consulte a devolução ou contestação no aplicativo do seu banco ou cartão.</p>':'')+
    (active&&p.code?'<img class="pix-qr" src="/api/track/'+encodeURIComponent(token)+'/pix.svg" alt="QR Code Pix deste pedido" width="220" height="220"><div class="pix-key"><code>'+esc(p.code)+'</code><button id="online-copy-code" class="btn secondary small">Copiar Pix</button></div>':'')+
    (active&&p.expires?'<p class="muted">Validade: '+date(p.expires)+'. A confirmação aparece aqui automaticamente.</p>':'')+
    (active&&p.needs_email?'<label>E-mail para o pagamento<input id="online-email" type="email" autocomplete="email" maxlength="254" required></label>':'')+
    (active&&checkoutUrl(p.checkout_url)?'<button class="btn" id="online-checkout">Pagar no Mercado Pago</button><p class="muted">Você informa os dados do cartão na página segura do Mercado Pago.</p>':active&&(p.can_retry||['creating','uncertain'].includes(p.status))&&!p.code?'<button class="btn" id="online-start">'+(['creating','uncertain'].includes(p.status)?'Conferir tentativa':pix?'Gerar Pix':'Abrir pagamento seguro')+'</button>':'')+
    (active&&['creating','uncertain'].includes(p.status)?'<p class="notice">Estamos conferindo a cobrança. Aguarde a atualização para evitar pagar duas vezes.</p>':'')+'</section>';
}
export function bindTrackingPayment(o,token,refresh){
  const p=o.online_payment;if(!p)return;
  if($('#online-copy-code'))$('#online-copy-code').onclick=()=>copy(p.code);
  if($('#online-checkout'))$('#online-checkout').onclick=()=>{const url=checkoutUrl(p.checkout_url);if(url)location.assign(url);};
  if($('#online-start'))$('#online-start').onclick=async e=>{
    const email=$('#online-email');if(email&&!email.reportValidity())return;
    e.currentTarget.disabled=true;
    try{const r=await api('/api/track/'+encodeURIComponent(token)+'/payment',{method:'POST',body:JSON.stringify({payment_email:email?.value.trim()||''})});const url=checkoutUrl(r.payment?.checkout_url);if(url)location.assign(url);else await refresh();}
    catch(error){toast(error.message);if($('#online-start'))$('#online-start').disabled=false;}
  };
}

export function merchantPayment(o,role){
  const p=o.online_payment;if(!p)return '';
  return '<section class="notice online-merchant"><b>'+esc(paymentLabel(p))+'</b><p>'+ (p.review?'Confira no Mercado Pago antes de receber novamente.':p.paid?'Pagamento conferido com o Mercado Pago.':'A preparação aguarda a confirmação do pagamento online.')+'</p><div class="row-actions"><button type="button" id="online-verify" class="btn secondary small">Conferir pagamento</button>'+(p.paid&&role==='owner'?'<button type="button" id="online-refund" class="btn secondary small">Estornar pagamento</button>':'')+'</div></section>';
}
export function bindMerchantPayment(o,reload){
  if($('#online-verify'))$('#online-verify').onclick=async e=>{e.currentTarget.disabled=true;try{await api('/api/admin/orders/'+o.id+'/payment/check',{method:'POST'});closeModal();await reload();toast('Pagamento conferido.');}catch(error){toast(error.message);if($('#online-verify'))$('#online-verify').disabled=false;}};
  if($('#online-refund'))$('#online-refund').onclick=()=>{
    modal('Estornar '+money(o.total)+'?','<p>O valor integral do pagamento do pedido #'+o.number+' será devolvido pelo Mercado Pago. O cancelamento do pedido é uma ação separada.</p><p>Confirme o pedido e o cliente antes de continuar.</p><div class="dialog-actions"><button class="btn danger" id="online-refund-confirm">Confirmar estorno integral</button><button class="btn secondary" id="online-refund-back">Voltar</button></div>');
    $('#online-refund-back').onclick=()=>{closeModal();reload();};
    $('#online-refund-confirm').onclick=async e=>{e.currentTarget.disabled=true;try{await api('/api/admin/orders/'+o.id+'/payment/refund',{method:'POST',body:JSON.stringify({confirm:true})});closeModal();await reload();toast('Solicitação conferida. Consulte a situação do pagamento.');}catch(error){toast(error.message);if($('#online-refund-confirm'))$('#online-refund-confirm').disabled=false;}};
  };
}
