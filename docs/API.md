# API

Frontend e API no mesmo host. Valores monetários são inteiros em centavos (BRL). Datas são ISO 8601 UTC; a interface usa America/Sao_Paulo. Erros retornam um objeto {"error":"Mensagem"} com código HTTP.

## Sessão

GET /api/session retorna csrf, user (ou null) e registration. Mantenha o cookie e envie X-CSRF-Token em toda requisição POST, PUT, PATCH ou DELETE. Login, cadastro e alteração de senha retornam um csrf novo. Não há CORS público. A origem precisa corresponder a PUBLIC_URL quando definida.

## Público

| Método | Endpoint | Função |
| --- | --- | --- |
| GET | /health | Saúde do serviço e banco |
| GET | /api/session | Sessão atual e CSRF |
| POST | /api/auth/register | name, email, password, store_name, slug |
| POST | /api/auth/login | email, password |
| POST | /api/auth/logout | Encerrar sessão |
| GET | /api/store/:slug | Loja, categorias e produtos ativos |
| POST | /api/store/:slug/quote | Cotação validada pelo servidor |
| POST | /api/store/:slug/orders | Criar pedido |
| GET | /api/track/:token | Itens, total e status |

~~~json
{
  "customer": "Seu Nome",
  "phone": "11999999999",
  "mode": "delivery",
  "address": "Rua, número, bairro, cidade",
  "payment": "pix",
  "change_for": null,
  "notes": "",
  "coupon": "BEMVINDO10",
  "items": [
    {"product_id": 1, "quantity": 2, "option_ids": ["queijo"], "notes": "Sem cebola"}
  ]
}
~~~

Ao criar pedido envie Idempotency-Key: 16–100 caracteres alfanuméricos, hífen ou sublinhado (ex.: UUID). Retentar o mesmo corpo/chave retorna o pedido existente sem reservar estoque novamente. Outra carga com a mesma chave retorna 409.

O servidor ignora totais do cliente e usa preços atuais. Desconto nunca supera subtotal. Taxa só vale para delivery. Troco só para cash. Pagamentos: pix, cash, card. Modos: delivery, pickup. /quote recebe items, mode e coupon; não reserva estoque nem consome cupom.

## Painel autenticado

| Método | Endpoint | Função |
| --- | --- | --- |
| GET / PUT | /api/admin/store | Configurações |
| POST | /api/admin/upload | multipart/form-data com file; retorna url WebP |
| GET / POST | /api/admin/products | Listar/cadastrar produtos |
| PUT / DELETE | /api/admin/products/:id | Editar/pausar |
| POST | /api/admin/categories | Cadastrar |
| DELETE | /api/admin/categories/:id | Remover; produtos vão para Outros |
| GET | /api/admin/orders | Ativos e histórico recente, até 500 registros |
| PATCH | /api/admin/orders/:id | status, paid, driver_id |
| GET / POST | /api/admin/drivers | Listar/cadastrar |
| PUT | /api/admin/drivers/:id | Editar/ativar |
| GET / POST | /api/admin/coupons | Listar/cadastrar |
| PATCH | /api/admin/coupons/:id | active (booleano) |
| GET | /api/admin/summary?days=7 | Períodos: 1, 7, 30 |
| POST | /api/admin/expenses | description, amount |
| DELETE | /api/admin/expenses/:id | Excluir |
| GET | /api/admin/export | CSV |
| PUT | /api/auth/password | current_password, new_password |

GET /api/admin/orders?status=completed (ou outro estado) consulta até 500 pedidos daquele estado. A loja é identificada pela sessão; IDs do cliente não concedem acesso a outra loja.

Produto: name, description, price, category_id (ou null), image (HTTPS ou /media/…), active, featured, stock (inteiro ou null), position, extras, unit_cost (centavos ou null), low_stock (limite de alerta). Complementos: id, name, price, unit_cost (centavos ou null). IDs únicos por produto. Custos são privados e não aparecem no cardápio nem no acompanhamento público.

Ao editar um produto, envie `expected_stock` com o estoque que foi carregado no formulário. Se `stock` continuar igual a esse valor, o servidor preserva o estoque atual, que pode ter mudado por uma venda. Se a edição alterar a quantidade e o saldo tiver mudado desde a leitura, retorna 409; recarregue antes de tentar novamente. Use o endpoint de ajuste para reposições e perdas.

Cupom: code, kind (percent ou fixed), value (percentual inteiro ou centavos), minimum (centavos), expires (YYYY-MM-DD ou vazio), max_uses (inteiro ou null). Uso incrementa na criação de pedido e é devolvido no cancelamento.

## Fluxo

Entrega: new → preparing → ready → delivering → completed.

Retirada: new → preparing → ready → completed.

Estados ativos podem ir para cancelled. Cancelamento devolve estoque e uso do cupom uma única vez. Concluídos/cancelados não voltam para estados ativos.

paid é confirmação manual do lojista, independente do status. Cancelar não faz reembolso. Relatórios excluem cancelados e agrupam recebimentos pela criação do pedido, não pela liquidação bancária.

## Limites

Body: 8 MB. Pedido: 50 linhas, 50 unidades por linha. Produto: 12 complementos.
Rate limits por IP, persistidos no SQLite: login 15/10 min; cadastro 5/h; pedidos 30/10 min; cotação 120/10 min.

O frontend envia expected_total com o total aprovado na cotação. Se preços, descontos ou taxa mudarem antes da gravação, o servidor retorna 409 e a interface atualiza a cotação para nova confirmação.

## Financeiro, clientes e estoque

Todos estes endpoints exigem a sessão do lojista e CSRF nas alterações. Os períodos de gestão aceitam `days=1|7|30|90|365`, a partir da meia-noite em São Paulo, agrupados pela criação do pedido.

| Método | Endpoint | Função |
| --- | --- | --- |
| GET | /api/admin/finance?days=30 | Vendas concluídas, custos, margem, cobertura e pedidos para conferência |
| PUT | /api/admin/finance/settings | payment_fees: pix/cash/card em pontos-base (250 = 2,5%); default_delivery_cost em centavos ou null |
| PATCH | /api/admin/orders/:id/costs | delivery_cost, payment_fee e items: [{id,unit_cost}]; custos absolutos em centavos ou null |
| GET | /api/admin/insights | Resumo de 7 dias, mais vendidos, estoque baixo e preparação da loja |
| GET | /api/admin/customers | Até 1.000 clientes agregados por telefone |
| GET | /api/admin/customers/:phone/orders | Até 100 pedidos recentes do cliente da própria loja |
| GET | /api/admin/stock | Produtos e últimas 100 movimentações |
| POST | /api/admin/stock/:id/adjust | delta inteiro e reason; exige controle de estoque ativo, não permite saldo negativo |
| POST | /api/admin/orders | Pedido de balcão/telefone com o corpo e Idempotency-Key do pedido público; usa somente a loja autenticada |

Os custos dos produtos, complementos, entrega, pagamento e comissão são gravados com cada venda. Alterar a configuração depois não recalcula pedidos anteriores. O lucro estimado usa pedidos concluídos menos custos e despesas operacionais do período. Se qualquer pedido concluído tiver custos desconhecidos, `estimated_profit` e `margin` retornam null. Zero informado é diferente de custo desconhecido.

Despesas recebem `category: operating|inventory`. Compras de estoque aparecem no caixa, mas não são descontadas novamente do lucro: o CMV usa o custo das unidades vendidas. Registre mensalidades, impostos e outros gastos como despesas operacionais. Nenhuma apuração fiscal ou cobrança bancária é executada.

## Dono da plataforma

Página `/plataforma`; somente contas com `platform_admin` concedido por um operador. Cadastro e configurações do lojista não concedem esse papel. Sessão e CSRF continuam obrigatórios.

| Método | Endpoint | Função |
| --- | --- | --- |
| GET | /api/platform/summary?days=30 | Lojas, contratos, vendas, comissões, recebimentos, despesas, caixa e histórico administrativo |
| PUT | /api/platform/stores/:id | commission_bps (0–10000), monthly_fee (centavos), enabled (booleano) |
| POST | /api/platform/ledger | kind: receipt/expense, store_id, description, amount; requer Idempotency-Key |
| DELETE | /api/platform/ledger/:id | Anula o lançamento, preservando o histórico; repetir não subtrai novamente |

Recebimentos exigem uma loja; despesas podem ser da plataforma ou de uma loja. A mesma chave e corpo retornam o lançamento já criado; corpo diferente retorna 409. Mensalidade é valor contratado, comissão é uma previsão sobre produtos após desconto em novos pedidos, e receita efetivamente recebida vem dos lançamentos. As vendas dos lojistas pertencem aos lojistas. Suspender uma loja fecha o cardápio e bloqueia novos pedidos e uso da API, preservando acesso do lojista ao histórico.

## Integração de entregas

O contrato completo, exemplos curl, tratamento de erros e ciclo de consulta estão em [`/static/api-docs.html`](../static/api-docs.html). No painel do lojista, **Integrações** permite criar e revogar chaves. Não existe uma chave global compartilhada entre lojas.

| Método | Endpoint | Autorização |
| --- | --- | --- |
| GET | /api/admin/integrations | Sessão do lojista |
| POST | /api/admin/integrations/keys | Sessão + CSRF; name e scopes; até 10 chaves ativas |
| DELETE | /api/admin/integrations/keys/:id | Sessão + CSRF; revogação imediata |
| GET | /api/v1/store | Bearer; orders:read |
| GET | /api/v1/deliveries?after=0 | Bearer; orders:read; apenas entregas ready/delivering, até 100 por página |
| POST | /api/v1/deliveries/:id/claim | Bearer; deliveries:write; external_id, provider e delivery_cost opcional |
| POST | /api/v1/deliveries/:id/events | Bearer; deliveries:write; event_id e status delivering/completed |

Use `Authorization: Bearer sca_...`. A chave completa aparece uma vez; o banco guarda apenas hash e prefixo. Limite de 120 requisições por minuto por chave, independente de IP. A autorização Bearer dispensa CSRF exclusivamente em `/api/v1/`; não concede acesso a rotas administrativas. Endereços e telefones de entrega são dados privados autorizados ao parceiro; custos internos e confirmação de pagamento não são expostos.

Vincule somente pedidos prontos para entrega. Repetir o vínculo com a mesma chave/parceiro/id externo é idempotente. Eventos exigem vínculo da mesma chave e seguem ready → delivering → completed. O mesmo event_id/corpo não repete a transição; corpo diferente retorna 409. Integração não confirma pagamento e não cancela pedidos. O parceiro deve impedir duplicação da corrida antes do claim, manter os ids externos e deduplicar eventos. O MotoJá ainda precisa de um adaptador no próprio servidor; não há envio automático somente por gerar uma chave.
