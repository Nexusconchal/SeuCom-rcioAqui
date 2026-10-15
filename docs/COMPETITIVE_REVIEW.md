# Histórico da primeira comparação

Esta análise descreve a primeira etapa e foi substituída pela [revisão operacional atual](EXPANSION_REVIEW.md). Suas lacunas não representam o estado atual.

# SeuComércioAqui: comparação e evolução

Análise do código em 14 de outubro de 2026 e das páginas oficiais dos três concorrentes. Recursos anunciados podem depender de planos e habilitação. Não houve acesso autenticado aos painéis privados dos concorrentes nem validação das integrações em produção. `/painel` respondeu HTTP 200, mas exige login para operar.

## O seu produto já tinha mais do que o print mostrava

O repositório contém Pix online/Mercado Pago, avisos de status por WhatsApp/Evolution, conexão automática com MotoJá, fidelidade por pedidos, agendamento, avaliações, repetir pedido, complementos e escolhas, cozinha, estoque de produtos, clientes, custos históricos, relatórios, equipe/permissões, assinatura e administração da plataforma. Presença no código não confirma que credenciais e serviços estejam configurados em produção.

Fidelidade concede desconto depois de um número de pedidos concluídos; não é carteira de cashback. Mensagens de status pelo WhatsApp não são um robô que conversa e monta pedidos. QR do cardápio não identifica mesa/comanda.

## Lacunas tratadas nesta alteração

| Necessidade | Implementação | Limite |
| --- | --- | --- |
| Vender adicionais na sacola | Até 12 sugestões escolhidas pelo lojista; até 3 disponíveis e ainda fora da sacola aparecem | Opções obrigatórias passam pelo formulário; nenhum item entra sozinho |
| Mostrar recompensa antes da compra | Faixa de fidelidade no cardápio | Usa o desconto por pedidos já existente |
| Conhecer o público | Primeira compra, recorrentes, VIP com 5 compras e inativos há 30 dias; gasto e ticket de pedidos concluídos | Regras explícitas, sem classificação por IA |
| Preparar campanhas | Rascunhos e prévia com nome, loja, link e clientes autorizados | Envio individual; prévia de até 100 destinatários |
| Recuperar sacolas | Consentimento separado, espera de 30 minutos, link assinado de 7 dias e preços atuais | Lista de até 100 sacolas; lojista revisa e envia o lembrete |
| Medir conversão | Visita → sacola → checkout → pedido criado; últimos 30 dias | Sessões anônimas, sem atribuição a anúncios ou receita |
| Controlar ingredientes | kg/l/un, 3 casas decimais, alertas, ajustes e histórico | Compra de insumo altera o estoque; a despesa financeira é lançada separadamente |
| Ficha técnica e custo | Receita por unidade, capacidade pelo insumo limitante e custo registrado no pedido | Receita base; complementos mantêm seus custos próprios |
| Evitar venda sem insumo | Reserva transacional do consumo total da sacola | Inclui ingredientes compartilhados entre produtos |
| Cancelar corretamente | Devolução do consumo original, uma única vez | Receita e preço novos não alteram a reserva ou custo histórico |

As telas mantêm verde-petróleo, laranja, cartões claros e navegação existente, com adaptação a celular, tablet e desktop. Não foram copiados código, marcas ou telas dos concorrentes.

## O que continua faltando

| Área | Referência dos concorrentes | Próximo trabalho |
| --- | --- | --- |
| Atendimento automático | Anota AI anuncia robô multicanal com áudio; Cardápio Web/Beefood anunciam automação e IA | Provedor de mensagens/IA, conversas persistidas, catálogo/preços do servidor, passagem para atendente e pedidos sem duplicação |
| Salão | Mesas, comandas, QR por mesa, garçom | Conta aberta, inclusão concorrente de itens, transferência/divisão, taxa de serviço e fechamento |
| Fiscal | NFC-e/NF-e | Provedor, dados/certificado do estabelecimento, configuração e homologação. A notinha atual não é documento fiscal |
| Marketplaces | Beefood/Cardápio Web anunciam centralização | Acesso oficial ao parceiro, catálogo vinculado e webhooks. A API de entregas não substitui integração com iFood |
| Pagamento online completo | Cartão; Anota AI também anuncia carteiras digitais | Checkout hospedado/tokenização, estorno e conciliação pelo provedor |
| Cashback | Benefício anunciado pelos concorrentes | Saldo por cliente autenticado, regras de ganho/expiração/uso e estorno; separado da fidelidade por pedidos |
| Marketing automático | Campanhas/recuperação automatizadas | Provedor autorizado, opt-out, fila durável, limites e deduplicação. O módulo desta entrega é manual |
| Impressão profissional | Impressoras por setor e equipamentos | Agente local/drivers, cozinha/bar e recuperação de falhas |
| Logística nacional | Rotas e gestão de entregadores | Integrações por fornecedor, áreas geográficas e roteirização; MotoJá é uma conexão específica |
| Financeiro ampliado | Contas a pagar/receber, compras, fornecedores e DRE | Vencimentos, pagamentos parciais, conciliação e ligação compra → estoque → caixa |
| Escala nacional | Operação em regiões e formatos diferentes | Fuso por loja: hoje America/Sao_Paulo é fixo. Disponibilidade, backups/restauração e carga real antes de prometer SLA |

## Ordem de evolução proposta

1. Pilotar esta entrega em Conchal: compra real, cancelamento, receita/estoque e adesão às sugestões. Comparar conversão e ticket sem usar dados fictícios como promessa de aumento.
2. Completar salão e emissão fiscal para restaurantes que dependem desses fluxos.
3. Construir atendimento WhatsApp com fila durável, passagem para atendente e preços do servidor.
4. Integrar marketplaces e pagamentos completos após obter acesso oficial aos parceiros.
5. Ajustar operação por região: fuso, disponibilidade, restauração e teste de pedidos simultâneos.

Ser superior precisa aparecer na operação: pedido não perdido, estoque e caixa consistentes, compra rápida no celular e suporte que resolve. A entrega fecha lacunas importantes, mas ainda não estabelece equivalência com todas as funções anunciadas pelos concorrentes.

## Fontes oficiais

- [Beefood: planos](https://ajuda.beefood.com.br/planos-e-precos) e [gestão](https://beefood.com.br/sistema-de-gestao/).
- [Cardápio Web: funcionalidades](https://cardapioweb.com/funcionalidades/), [plataforma](https://cardapioweb.com/) e [ficha técnica](https://ajuda.cardapioweb.com/modulos-do-sistema/estoque-avancado).
- [Anota AI: recursos](https://anota.ai/home/funcionalidade/cupom-de-desconto/) e [cardápio e pagamentos](https://anota.ai/home/funcionalidade/cardapio-digital/).

## Verificação

Novos testes cobrem reserva concorrente, rollback, custos históricos, cancelamento depois de alterar receita, isolamento entre lojas/funções, CSRF, consentimento, telefone normalizado, links assinados, anonimização e recuperação em outra sessão sem duplicar conversão. O navegador exercita configuração, compra com sugestão, consentimento, conclusão, campanha e recuperação, além de 390, 768 e 1440 px. O workflow também inclui os testes novos em PostgreSQL e Windows.
