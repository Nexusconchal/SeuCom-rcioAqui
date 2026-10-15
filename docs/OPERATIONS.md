# Guia dos novos módulos

1. **Caixa por turno**: abra com fundo de troco. Receba parcelas na forma confirmada; informe o valor aplicado ao pedido, descontando troco. Sangria/suprimento movimentam dinheiro fora de venda. Ao fechar, conte só dinheiro; diferença precisa de explicação.
2. **PDV / Balcão**: F2 busca, clique adiciona/opções, F9 finaliza. Nome tem padrão Consumidor; telefone é opcional no balcão. Entrega exige contato/endereço e CEP se houver cobertura por CEP. Receba no Caixa quando confirmado.
3. **Mesas e comandas**: abra, lance pelo PDV da mesa, prepare e receba. Encerrar exige pedidos concluídos/quitados e estorno de cancelados. Transferir exige mesa livre.
4. **Cozinha**: o setor do produto é copiado para a venda. Cada setor prepara itens; o último libera o pedido. Ações da visão Todos os setores coordenam o pedido inteiro. Impressão do setor é via de produção sem total financeiro parcial.
5. **Imprimir notinha**: setor vale para esta loja neste navegador. Vazio imprime completa; preenchido imprime produção correspondente. Automática exige painel aberto e configuração da impressora/navegador.
6. **Insumos e fichas**: estoque sempre com motivo; ficha base e de adicional. 150 g = 0,150 kg. Cancelamento devolve consumo original. Dividir receita entre sabores só quando cada ficha representa produto inteiro.
7. **Contas e fornecedores**: vencimentos, categoria e baixas parciais. Conta a pagar gera despesa; estoque não duplica despesa operacional/CMV. Ficha de produção obtém 1 kg/l/un; lote consome matéria-prima e atualiza custo médio. Fiado exige limite por telefone e recebimento no Caixa.
8. **Promoções e horários**: fuso, aceite e regras. Agendados/Pix online não têm aceite automático imediato. Maior prioridade vence, empate usa regra nova. Horários iguais: dia inteiro; madrugada pertence ao dia inicial.
9. **Marketing**: público, prévia, rascunho e agendamento pelo lojista. Autorização conferida antes do envio. Cancelar impede mensagens ainda não iniciadas. Resultado incerto exige conferência no WhatsApp; não é reenviado. Sacolas continuam individuais.
10. **Atendimento WhatsApp**: conecte em Integrações e ative conversas. CARDÁPIO/MENU/HORÁRIO são opcionais. ATENDENTE pausa bot. Assuma antes de responder. Na fila permanece até worker confirmar. Encerrar libera responsável; nova mensagem reabre. Exclusão pela gestão remove painel, não o WhatsApp.
11. **Cashback**: WhatsApp e percentual até 20%. Crédito sobre produtos após desconto, sem entrega, liberado após conclusão/pagamento. Cliente confirma telefone. Cancelamento restitui resgate. Reversão de pagamento deixa o crédito da venda indisponível.
12. **Mapa de entregas**: CEP, link individual e posição iniciada/parada pelo entregador. Gerar/revogar invalida anterior. Posição antiga é identificada. Selecione prontos para lote. Destino opcional informado pelo cliente; confira endereço.
13. **Minha rede**: crie, convide pelo final do link da unidade; só seu dono pode aceitar em 7 dias. Reúne cardápios públicos sem compartilhar gestão financeira.
14. **Gerar relatório**: dias, mês ou datas até 366 dias; PDF/Excel/CSV. Resumos de recebimento são saldos dos pedidos criados no período; tabela de recebimentos/estornos usa operação. Confira com extratos/comprovantes.

## Worker de WhatsApp

PDV, caixa, salão, cozinha, estoque, contas, fiado e relatórios funcionam sem worker. Campanhas agendadas/respostas precisam dele. Código do cashback usa envio direto pela conexão existente.

Configure `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `PUBLIC_URL` HTTPS, `SECRET_KEY`, `DATABASE_URL` e `DATABASE_SCHEMA`. Conecte instância por loja. `/webhook/set/:instance` recebe segredo em `X-Webhook-Token`; grupos, mensagens próprias e instância diferente são ignorados. Valide a versão real da Evolution em homologação.

Worker separado usa **mesmo PostgreSQL, schema e SECRET_KEY** da aplicação. Não use SQLite em discos separados:

~~~sh
python marketing_worker.py
~~~

Em Render, é um Background Worker Python com essas variáveis, sem tráfego HTTP. Nenhum recurso/cobrança de hospedagem foi criado nesta revisão. SIGTERM interrompe novas rodadas e aguarda operação (timeout do provedor 15 s); permita ao menos 60 s para encerrar.

Rodadas manuais de teste:

~~~sh
flask --app app:create_app marketing-dispatch --limit 1
flask --app app:create_app inbox-dispatch --limit 1
~~~

**Enviam mensagens reais se houver conexão/fila.** Não execute contra produção como teste. Interrupção pode ocorrer depois de entregar a mensagem; após 5 min o resultado fica incerto, sem reenvio automático.

## Publicação

Migrações são aditivas; itens antigos herdam a etapa do pedido, próximos preservam progresso individual. PostgreSQL aplica RLS/revogação de PUBLIC e de anon/authenticated quando existirem. Credenciais de backend ficam no servidor. Use backup, migração do schema privado e validação antes de publicar. Este guia descreve código revisável, sem confirmar publicação ou configuração de provedores. Limites em `EXPANSION_REVIEW.md`.
