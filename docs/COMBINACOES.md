# Sugestões por produto

Em **Painel → Marketing → Sugestões por produto**, escolha o produto principal,
adicione até seis produtos, ajuste a ordem e salve. Uma prévia mostra a sequência.
Trocar o seletor preserva o rascunho enquanto a página continua aberta; sair da
página ou recarregar descarta alterações não salvas.

No cardápio, após adicionar o principal, o cliente vê as combinações disponíveis.
Escolher uma sugestão abre os detalhes normais, inclusive escolhas obrigatórias,
complementos, quantidade e observações. Nenhum item é adicionado automaticamente.
A sacola também mostra até três combinações disponíveis; quando não houver,
permanecem as sugestões gerais já configuradas. Itens já na sacola, inativos,
ocultos pelas regras do canal/horário e com estoque zero não são oferecidos.

## Como ler o relatório

O bloco **O que suas sugestões venderam** permite consultar 7, 30 ou 90 dias
corridos. Considera pedidos **criados** no período e atualmente concluídos.
Pedidos pendentes/cancelados ficam de fora. As métricas são:

- Pedidos distintos com ao menos um item atribuído a uma combinação.
- Quantidade desses itens, incluindo múltiplas unidades escolhidas pelo cliente.
- Valor bruto dos itens com complementos, antes dos descontos do pedido e sem
  frete. Não representa lucro, caixa recebido ou aumento causal das vendas.
- Até 100 combinações, ordenadas pelo valor bruto. Totais incluem todas.

A atribuição só é aceita quando a oferta foi assinada pelo servidor, pertence à
mesma loja e produto, tem até sete dias, a relação ainda existe no catálogo e o
produto principal permanece no pedido. Metadata ausente/alterada/expirada não
impede uma compra válida; apenas não gera atribuição. As regras normais de preço,
opções, reservas de estoque e idempotência continuam obrigatórias.

Os nomes são gravados no pedido para preservar o histórico após mudanças no
catálogo. Vendas anteriores à funcionalidade, sugestões gerais, itens adicionados
diretamente pela vitrine e sacolas recuperadas pelo link não recebem atribuição
retroativa. Não há taxa de conversão de ofertas, pois impressões não são medidas.

## Operação e dados

- Donos e gerentes configuram e consultam; caixa e cozinha não têm acesso.
- APIs privadas: `GET /api/admin/marketing/combinations`,
  `PUT /api/admin/marketing/combinations/<produto>`,
  `GET /api/admin/marketing/combinations/report?days=30`.
- Migração aditiva e repetível em `migrations.py`: `products.suggestion_ids`,
  `order_items.suggested_by`, `order_items.suggested_by_name`. Sem novas tabelas,
  sem retropreenchimento e sem mudança nas permissões/RLS do esquema privado.
- `tests/test_upsell.py` cobre isolamento, permissões, assinatura, expiração,
  disponibilidade, preço, complementos, estoque, histórico e relatório.
- `tests/test_upsell_browser.py` percorre configuração, reordenação, rascunho,
  compra móvel com complemento, persistência da sacola e relatório. Capturas
  geradas em `artifacts/combinacoes-*.png` usam somente dados fictícios locais.
