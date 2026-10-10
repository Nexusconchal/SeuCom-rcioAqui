# Revisão funcional — outubro de 2026

A referência do PediPlus veio das capturas fornecidas pelo proprietário. A pesquisa do [Cardápio Web](https://cardapioweb.com/) e da sua [documentação de desempenho](https://ajuda.cardapioweb.com/gestao/desempenho) orientou prioridades de operação: pedidos, produção, estoque, clientes, financeiro e integrações. A interface mantém a identidade do SeuComércioAqui. Não houve cópia de código, marca ou telas dos concorrentes.

## Entregue nesta revisão

| Necessidade | Comportamento implementado |
| --- | --- |
| Administrar o SaaS | Área exclusiva do dono com lojas, contratos, habilitação, mensalidades, comissões e histórico |
| Saber quanto a plataforma recebe | Lançamentos manuais de recebimentos e despesas, resultado geral e por loja, repetição segura e anulação com histórico |
| Entender lucro do lojista | Custos históricos por item e complemento, entrega e pagamento; custos pendentes deixam o lucro a informar |
| Organizar produção | Tela de cozinha com itens, quantidades, complementos, observações e avanço do preparo |
| Receber pedido por telefone | Cadastro de balcão com preço e estoque validados pelo servidor |
| Controlar mercadoria | Limite de estoque baixo, reposição/perda com motivo, histórico de vendas e devolução no cancelamento |
| Conhecer os compradores | Busca de clientes, total comprado e histórico da própria loja |
| Integrar entregas | API por loja com permissões, revogação, paginação, vínculo idempotente e eventos deduplicados |
| Operar no celular | Navegação com todas as seções, formulários e tabelas com rolagem local; testes em 390, 768 e 1440 px |

## Conexão com o MotoJá

O MotoJá já possui operação de empresas e conectores de outros cardápios. Esta revisão entrega o contrato do lado SeuComércioAqui. Para completar a colaboração, um adaptador no backend MotoJá precisa autenticar a empresa, guardar sua chave de forma privada, consultar pedidos prontos, criar uma corrida com deduplicação, vincular o id externo e devolver os eventos de coleta/conclusão.

Criação de corridas pode reservar saldo e notificar entregadores no MotoJá. Essa parte precisa de ambiente de teste próprio e validação de taxas, cancelamentos, reconexão e corridas já em andamento. Não foi publicada uma alteração no aplicativo parceiro nesta revisão. A tela indica **Conector do MotoJá pendente**.

## Preparação para vender até dezembro

1. **Piloto com comércios reais:** cadastrar produtos e custos, simular entrega/retirada e fechamento de caixa; observar pedidos simultâneos, falhas de internet e facilidade de operação durante um turno.
2. **Conector MotoJá:** implementar no parceiro e testar criação única, atualização de status, falhas e recuperação sem corridas ou cobranças repetidas.
3. **Operação comercial:** definir planos e contrato, processo de suporte, recuperação/verificação de e-mail e política de privacidade com tratamento dos dados dos clientes.
4. **Cobrança:** manter recebimentos manuais no piloto ou integrar um provedor para assinaturas, notificações assinadas e conciliação. Contrato configurado ainda não cobra automaticamente.
5. **Disponibilidade e recuperação:** testar restauração de backup e acompanhar uso real. A publicação atual usa planos gratuitos com suspensão por inatividade; reavaliar infraestrutura quando houver clientes que dependem do serviço no horário de funcionamento.

Fidelidade, emissão fiscal, WhatsApp automático e integrações iFood/Anota AI não fazem parte desta entrega. Devem entrar conforme demanda validada e acesso aos programas/documentações oficiais dos parceiros. A nova marca visual continua sujeita à aprovação do proprietário.
