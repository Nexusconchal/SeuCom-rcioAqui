import { $$, esc, money, date, statuses } from './ui.js';

export function renderCustomer(target, value, createOrder){
  const {customer,summary,orders}=value;
  target.innerHTML='<div class="inbox-customer-heading"><span class="eyebrow">CLIENTE E PEDIDOS</span><h2>'+esc(customer.name)+'</h2><p>'+esc(customer.phone)+'</p></div>'+
    '<div class="inbox-customer-stats"><div><strong>'+summary.orders+'</strong><span>pedidos válidos</span></div><div><strong>'+money(summary.spent)+'</strong><span>compras concluídas</span></div></div>'+
    '<p class="inbox-customer-note">'+(summary.orders>1?'Cliente recorrente':summary.orders===1?'Primeiro pedido registrado':'Ainda sem pedidos nesta loja')+(summary.active?' • '+summary.active+' em andamento':'')+'</p>'+
    '<div class="section-heading"><h3>Pedidos recentes</h3><span class="badge gray">'+orders.length+'</span></div>'+
    (orders.length?orders.map(o=>'<details class="inbox-customer-order" '+(!['completed','cancelled'].includes(o.status)?'open':'')+'><summary><span><b>#'+o.number+'</b><small>'+date(o.created_at)+'</small></span><span><b>'+money(o.total)+'</b><small>'+esc(statuses[o.status]||o.status)+'</small></span></summary><div class="inbox-order-content"><ul>'+o.items.map(i=>'<li><b>'+i.quantity+' × '+esc(i.name)+'</b>'+(i.options.length?'<small>'+i.options.map(esc).join(' • ')+'</small>':'')+'</li>').join('')+'</ul><p>'+esc({pix:'Pix',pix_online:'Pix online',card_online:'Cartão online',cash:'Dinheiro',card:'Cartão',credit:'Fiado',wallet:'Carteira'}[o.payment]||o.payment)+' • '+(o.paid?'Pago':'Conferir pagamento')+'</p><p>'+esc(o.mode==='delivery'?'Entrega: '+o.address:'Retirada no estabelecimento')+'</p><button type="button" class="text-link" data-order-prefill="'+o.id+'">Usar cliente e endereço em novo pedido</button></div></details>').join(''):'<div class="inbox-context-empty"><p>O histórico aparece aqui quando este número fizer um pedido.</p></div>')+
    '<p class="inbox-customer-footnote">Até 8 pedidos recentes desta loja. Dados anteriores são uma referência; confirme o endereço com o cliente.</p>';
  $$('[data-order-prefill]',target).forEach(b=>b.onclick=()=>{
    const order=orders.find(o=>o.id===Number(b.dataset.orderPrefill));
    createOrder({customer:order.customer,phone:customer.phone,address:order.address,mode:order.mode});
  });
}
