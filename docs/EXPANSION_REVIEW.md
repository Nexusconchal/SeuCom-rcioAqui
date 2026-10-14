# Evolução operacional e comparação

Revisão de 14/10/2026. Referência: páginas oficiais, imagens de telas e trechos dos vídeos de PDV, mesas e estoque do BeeFood 3. Não houve acesso autenticado aos concorrentes. Recursos anunciados podem depender de planos/habilitação. Os testes usam lojas, clientes e provedores de comunicação fictícios.

| Área | Implementado | Limite e condição de uso |
| --- | --- | --- |
| PDV | Fotos, busca, categorias, escolhas, sacola, F2/F9 e pedidos ligados à cozinha/estoque | Recebimento no Caixa; sem TEF ou cartão online |
| Caixa por turno | Fundo, sangria, suprimento, conferência, diferença, histórico e autor | Dinheiro separado de Pix/cartão; pagamentos manuais não têm conciliação bancária automática |
| Recebimentos | Parciais, várias formas por pedido, estorno parcial vinculado ao original e idempotência | Registro não devolve dinheiro no banco; Pix online permanece conciliado pelo Mercado Pago |
| Salão | Mesas/comandas, abertura, pessoas, consumo, transferência, pagamentos e encerramento validado | Sem taxa de serviço, desconto da conta ou autoatendimento por QR da mesa |
| Cozinha | Setores, progresso por item e pedido pronto após todos os itens | Visão de todos os setores mantém ações do pedido inteiro |
| Impressão | Notinha, via do entregador, produção por setor e preferência por aparelho | Navegador; sem driver fiscal/ESC-POS ou gaveta |
| Ingredientes | kg/l/un em milésimos, alertas, movimentos, receita e reserva transacional | Entrada física e conta financeira são registradas separadamente |
| Adicionais/sabores | Quantidades, receita de opção, soma/maior preço/média, divisão opcional do consumo | Frações menores que um milésimo são arredondadas para cima na reserva agregada; ficha da opção é específica do produto |
| Preparos | Ficha de produção, lote, consumo de matéria-prima e custo médio | Sem produção em cascata ou cálculo automático de rendimento/perdas |
| Promoções | Preço/disponibilidade por dia, horário, datas, canal e prioridade | Conferência no servidor; agendados usam horário escolhido |
| CRM | Públicos padrão, condições E/OU salvas, recência, frequência, gasto, ticket e RFV | Regras explícitas; RFV não é previsão por IA |
| Campanhas | Prévia, rascunho, agendamento, fila persistente, cancelamento e histórico | Evolution/WhatsApp e worker; 100 destinatários/campanha, 60 tentativas/hora/loja, uma promoção/cliente/7 dias |
| Sacolas | Consentimento separado, lista após 30 min, link de 7 dias e preços atuais | Lembrete individual; sem disparos automáticos por abandono, aniversário ou segunda compra |
| Atendimento | Conversa, responsável, passagem para humano, resposta na fila, encerramento e exclusão pela gestão | Texto e indicação de mídia; bot de palavras-chave, sem montar pedido por IA |
| Cashback | Percentual líquido dos produtos, crédito após conclusão/pagamento, OTP e restituição da reserva no cancelamento | WhatsApp configurado; código 5 min/5 tentativas; sessão 30 min; saldo não sacável |
| Financeiro | Fornecedores, vencimentos, pagar/receber, baixas parciais e histórico | Sem CNAB, extrato bancário ou compra ligada automaticamente ao estoque |
| Fiado | Limite por cliente, validação transacional, vencimento e pagamento conciliado | Atendimento lança; cliente não escolhe crédito no cardápio público |
| Entrega | CEP, mínimo após desconto, frete grátis, bloqueios, lote, página do entregador e posição voluntária revogável | Mapa da posição selecionada/navegação por endereço; sem otimização, polígonos/raios ou geocodificação automática; atualização pelo botão |
| Rede | Página de unidades, convite dirigido, aceite do dono, remoção e saída | Logins, caixa e operação separados; sem financeiro consolidado de filiais |
| Relatórios | **Gerar relatório** separado; PDF, Excel, CSV, mês e datas | Vendas por criação do pedido; tabela de recebimentos por operação; custos desconhecidos continuam desconhecidos |
| Brasil | Fuso, horários, agendamento e relatórios por loja | Piloto, carga, restauração e observabilidade antes de prometer capacidade/SLA nacional |

Emissão de NFC-e/NF-e, integração oficial de pedidos com iFood/99/outros marketplaces, cartão online/TEF, drivers/gaveta e IA não foram implementados. Não há telas que simulem conexão com esses fornecedores.

Superar os concorrentes ainda exige validar operação em restaurantes, medir atendimento/conversão, implementar as lacunas explicitadas e testar carga/restauração. Quantidade de funções e imagens não comprovam superioridade operacional.

## Evidência

API: concorrência de estoque/pagamento/fiado, rollback, idempotência, custo/reserva histórica, estorno/conferência, isolamento, CSRF, consentimento, OTP, anonimização, convite dirigido, acesso revogável e produção por item. Navegador: PDV → pedido → pagamento parcial; mesa → consumo; regra; conta; PDF/Excel; cashback com código; GPS iniciado/parado; conversa assumida e resposta na fila. Comunicação usa provedor controlado; não comprova conexão real com WhatsApp.

## Referências

- BeeFood: [PDV](https://ajuda.beefood.com.br/pdv), [mesas](https://ajuda.beefood.com.br/mesas), [ficha](https://ajuda.beefood.com.br/ficha-tecnica), [estoque](https://ajuda.beefood.com.br/estoque-gestao-avancada), [campanhas](https://ajuda.beefood.com.br/campanhas-inteligentes-whatsapp), [WhatsApp](https://ajuda.beefood.com.br/whatsapp-atendimento-beebot), [planos](https://ajuda.beefood.com.br/planos-e-precos).
- Vídeos: [PDV](https://www.youtube.com/watch?v=iSm835le-XQ), [mesas](https://www.youtube.com/watch?v=YyczhJ1OV4A), [estoque](https://www.youtube.com/watch?v=cQsDvRz4EJA). Trechos inspecionados, não todos os minutos.
- [Cardápio Web](https://cardapioweb.com/funcionalidades/), [estoque avançado](https://ajuda.cardapioweb.com/modulos-do-sistema/estoque-avancado) e [Anota AI](https://anota.ai/home/funcionalidade/cardapio-digital/).
- Contrato do webhook: [Evolution EventDto](https://github.com/evolution-foundation/evolution-api/blob/main/src/api/integrations/event/event.dto.ts), [rota](https://github.com/evolution-foundation/docs-evolution/blob/main/v2/api-reference/webhook/set.mdx).
