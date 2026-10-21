# Pagamentos dos pedidos

## Ativação por loja

Em Configurações → Pagamentos, conecte a conta Mercado Pago do estabelecimento com a credencial de produção. Marque **Pix automático (QR Code)** e/ou **Cartão online (Mercado Pago)** e salve. Os recebimentos chegam à conta dessa loja. A cobrança da mensalidade usa outra credencial, da plataforma; veja [MENSALIDADE.md](MENSALIDADE.md).

O cliente informa seu e-mail para identificar o pagamento. No Pix, recebe o QR Code e o código copia e cola com validade. No cartão, abre o checkout hospedado pelo Mercado Pago. O app não recebe número, validade ou código de segurança do cartão. O checkout também pode oferecer saldo da conta Mercado Pago, conforme a disponibilidade do provedor; não se promete exclusividade de cartão.

Cartão na entrega/retirada e Pix manual continuam sendo modalidades diferentes, conferidas pela loja. Pagamentos online não podem ser confirmados pelo checkbox do pedido nem recebidos novamente no caixa manual.

## Confirmação e operação

- O pedido online com saldo a pagar aguarda confirmação antes de avançar para cozinha, entrega ou conclusão. Autoaceite só acontece depois de aprovação conferida; agendamentos preservam seu fluxo.
- O retorno do checkout e o conteúdo recebido no webhook não comprovam pagamento. O servidor consulta o Mercado Pago e verifica ID, referência da tentativa, moeda BRL, valor e conta recebedora.
- Tentativas têm chaves persistentes e histórico privado. Reconexões, notificações repetidas e retomada após erro de conexão reutilizam a identidade da cobrança. Um Pix anterior continua sendo reconhecido depois da renovação.
- Criações incertas são conferidas antes de repetir. Quando não é possível identificar com segurança o resultado anterior, a cobrança fica em conferência e não gera outra silenciosamente. Até cinco tentativas podem ser geradas por pedido, respeitando esses bloqueios.
- Cada cobrança é vinculada ao pedido e à loja no servidor. Credenciais por tentativa são criptografadas; não aparecem em respostas JSON, QR Codes, logs ou páginas do cliente.
- O botão **Conferir pagamento** consulta o provedor. **Link do pedido** copia o acompanhamento para o cliente concluir o pagamento.
- Duplicidade, devolução parcial, contestação e pagamento tardio de pedido cancelado exigem conferência. O pedido cancelado não é reaberto automaticamente.
- Pedido de valor final zero não cria cobrança no provedor nem fica preso aguardando pagamento.

## Cancelar e estornar

Cancelar pedido devolve o estoque e tenta cancelar a cobrança ainda pendente. Isso não inicia estorno de um pagamento aprovado.

O dono da loja pode abrir o pedido e usar **Estornar pagamento**. A interface exige uma segunda confirmação do valor integral. O servidor confere o pagamento novamente, usa uma chave estável de estorno e consulta o resultado. Pagamentos duplicados ou parcialmente devolvidos exigem conferência diretamente no provedor. A devolução efetiva e o prazo no cartão dependem do Mercado Pago e do banco emissor.

Cobranças abertas ou de resultado incerto impedem desconectar a conta ou trocar de recebedor. Credenciais históricas seladas permitem consultar e estornar um pagamento conhecido após desconexão. Se uma credencial foi revogada pelo Mercado Pago, a loja precisa restabelecer o acesso ou conferir diretamente no provedor.

## Publicação e verificação

A migração aditiva [pagamentos_migration.sql](pagamentos_migration.sql) cria duas tabelas privadas de tentativas/transações e adiciona o e-mail do pagador ao pedido. O runtime atualiza instalações SQLite/PostgreSQL de forma repetível; no Supabase, aplique a migração com o papel privado antes da publicação. As tabelas usam RLS e não concedem acesso às funções públicas do frontend.

Os testes exercitam cobrança Pix/cartão, retorno falsificado, quantia/recebedor/moeda divergentes, notificações repetidas, concorrência, expiração, falha de conexão, troca de conta, cancelamento durante criação, devolução e navegação em celular/desktop. O adaptador HTTP real é exercitado contra um servidor local. Não há cobrança, assinatura, cancelamento ou estorno financeiro real nos testes.

Produção exige credencial válida, conta habilitada para os meios escolhidos e conectividade com o Mercado Pago. A validação automatizada não substitui o credenciamento do estabelecimento.

## Referências públicas

O REA analisou artefatos públicos do Beefood como evidência de interface e comportamento. A implementação é própria e usa a API pública do fornecedor já integrado. Não usa código privado, credenciais ou endpoints internos dos concorrentes.

- [Beefood: cartão online Mercado Pago](https://ajuda.beefood.com.br/mercado-pago)
- [Anota AI: pagamento online iFood Pago](https://anota.ai/ajuda/pagamento-online-ifoodpago/)
- [Anota AI: pagamento online Tuna](https://anota.ai/ajuda/pagamento-online-tuna/)
- [Mercado Pago: Checkout Pro](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/overview)
- [Mercado Pago: notificações Webhooks](https://www.mercadopago.com.br/developers/pt/docs/your-integrations/notifications/webhooks)

Essas fontes não comprovam qual fornecedor processa todas as mensalidades dos concorrentes.
