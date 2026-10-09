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

Produto: name, description, price, category_id (ou null), image (HTTPS ou /media/…), active, featured, stock (inteiro ou null), position, extras. Complementos: id, name, price. IDs únicos por produto.

Cupom: code, kind (percent ou fixed), value (percentual inteiro ou centavos), minimum (centavos), expires (YYYY-MM-DD ou vazio), max_uses (inteiro ou null). Uso incrementa na criação de pedido e é devolvido no cancelamento.

## Fluxo

Entrega: new → preparing → ready → delivering → completed.

Retirada: new → preparing → ready → completed.

Estados ativos podem ir para cancelled. Cancelamento devolve estoque e uso do cupom uma única vez. Concluídos/cancelados não voltam para estados ativos.

paid é confirmação manual do lojista, independente do status. Cancelar não faz reembolso. Relatórios excluem cancelados e agrupam recebimentos pela criação do pedido, não pela liquidação bancária.

## Limites

Body: 8 MB. Pedido: 50 linhas, 50 unidades por linha. Produto: 12 complementos.
Rate limits por IP, persistidos no SQLite: login 15/10 min; cadastro 5/h; pedidos 30/10 min; cotação 120/10 min.
