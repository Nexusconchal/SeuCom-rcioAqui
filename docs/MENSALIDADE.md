# Mensalidade das lojas

A mensalidade usa a conta Mercado Pago da plataforma (`MP_PLATFORM_ACCESS_TOKEN`). O pagamento do pedido usa a conta conectada da própria loja. Esses recebimentos ficam separados. Esta alteração não configura credenciais nem inicia cobranças em produção.

## Cartão

- O lojista escolhe cartão e informa seu e-mail. Os dados do cartão são preenchidos no checkout hospedado do Mercado Pago; o SeuComércioAqui não recebe número ou código de segurança.
- A assinatura pendente é reutilizada. Tentativas simultâneas não criam outro contrato; o conector envia a chave de idempotência persistida.
- Se a criação retorna um erro de resultado incerto, a plataforma bloqueia outra criação até a conferência no Mercado Pago. Não se deve apagar a intenção de criação sem consultar o provedor: o contrato pode ter sido criado apesar do timeout.
- A autorização do cartão e a data agendada não comprovam pagamento. A loja fica liberada pelo teste gratuito ainda válido ou pelo período pago. O teste promocional da assinatura é concedido uma vez, depois da confirmação do contrato.
- Cada cobrança aprovada é consultada individualmente. A identidade do contrato, referência da loja, conta recebedora, moeda BRL, valor e frequência mensal precisam corresponder à intenção salva no servidor.
- O lojista pode atualizar a situação, abrir o gerenciamento do Mercado Pago e cancelar um contrato pendente, autorizado ou pausado. O período já pago continua válido após o cancelamento.

## Pix

- O Pix paga um mês por vez, sem recorrência automática. Um código válido é reutilizado. Na falha de criação, a tentativa posterior usa a mesma chave e o mesmo corpo, após um intervalo para evitar requisições paralelas.
- A tela mostra QR Code, copia e cola, contagem de validade e conferência automática. Fechar a janela interrompe a consulta daquela janela. Uma resposta atrasada não fecha outra janela do painel.
- Antes de gerar outro código, o servidor consulta o pagamento anterior. Uma assinatura no cartão ativa, pendente ou pausada precisa ser cancelada antes da mudança para Pix. Um Pix ainda válido ou cuja criação seja incerta impede iniciar outro contrato no cartão.
- O webhook e o botão de conferência consultam o Mercado Pago. O conteúdo recebido no webhook não é usado como prova de pagamento.
- A confirmação exige o ID, a referência, BRL, o valor original, a conta recebedora e o método Pix corretos. Alterar o preço global depois de gerar o código não altera o valor esperado daquele código.
- Uma confirmação tardia de um código antigo pode ser conciliada pelo ID salvo, sem apagar um código novo ainda pendente. A mesma confirmação gera um único lançamento, inclusive com requisições concorrentes.
- Um segundo mês efetivamente pago por Pix estende o período já pago, usando a regra atual de mês civil com três dias de tolerância.

## Datas e histórico

O histórico do lojista é exclusivo do dono da loja e mostra os últimos 12 recebimentos da mensalidade. `paid_at` registra o instante de aprovação informado pelo provedor, com fuso horário; a interface o apresenta no horário de Brasília. O instante de gravação continua separado. Uma data sem horário/fuso ou um lançamento manual não é convertido em uma aprovação bancária inventada.

Para Pix aprovado sem horário de aprovação, a data de criação verificada serve somente como referência do período. O horário de pagamento continua desconhecido. Para uma cobrança recorrente no cartão, a ausência de um instante válido de aprovação impede criar o recebimento automaticamente.

As intenções e os dados mínimos de conferência ficam em `platform_settings` com chaves privadas `billing.subscription.*`, `billing.pix.*` e `billing.creating.*`. Não armazenam dados brutos de cartão. Não há migração de esquema nesta melhoria.

## Limites operacionais

- A aprovação depende de conta e credencial válidas, disponibilidade do Mercado Pago e retorno das consultas. Os testes locais usam um provedor simulado; não comprovam credenciamento comercial ou produção.
- Pagamento com identidade ou valor divergente não libera a loja. Deve ser conferido no provedor e pelo suporte.
- A função não inicia estorno de mensalidade. Pagamentos devolvidos ou contestados não geram novo crédito, mas a revogação de um período concedido anteriormente precisa de conferência administrativa. Não há reconciliação automática de estornos da mensalidade nesta entrega.
- O reprocessamento automático de cartão busca o contrato atual da loja. Eventos de um contrato substituído e criações de cartão com resultado incerto exigem conferência administrativa antes de ajustes.
- O teste de R$ 1,00 permanece uma ação explícita exclusiva do dono da plataforma. Confere valor, conta, referência e método e não libera mensalidade. Nenhum teste real é executado na validação automatizada.

## Validação e referências

Testes de servidor cobrem divergência de valor/moeda/conta/referência/método, preços alterados, código antigo confirmado, registros concorrentes, checkout pendente reutilizado, falha incerta, datas verdadeiras e troca de meio de pagamento. Um teste de navegador cobre entrar no painel, gerar Pix, visualizar validade, confirmar com provedor simulado e verificar o histórico privado.

Documentação oficial usada para o contrato e as consultas:

- [Visão geral de Assinaturas](https://www.mercadopago.com.br/developers/pt/reference/online-payments/subscriptions/overview)
- [Consultar assinatura](https://www.mercadopago.com.br/developers/pt/reference/online-payments/subscriptions/get-preapproval/get)
- [Buscar pagamentos autorizados](https://www.mercadopago.com.br/developers/pt/reference/online-payments/subscriptions/authorized-payment-search/get)
- [Gerenciar assinatura](https://www.mercadopago.com.br/developers/pt/docs/subscriptions/subscription-management)
