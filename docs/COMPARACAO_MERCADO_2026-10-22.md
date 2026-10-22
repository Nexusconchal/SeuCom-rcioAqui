# Comparação de mercado — 22/10/2026

## Conclusão

O SeuComércioAqui já implementa cardápio, pedidos, PDV, caixa por turno, mesas, cozinha, estoque e fichas, entregas, marketing, atendimento WhatsApp e pagamento online. A prioridade é tornar esses fluxos simples de configurar, confiáveis em falhas e comprovados em operação real. A presença de módulos no código não comprova a mesma maturidade operacional dos concorrentes.

Pix e cartão dos pedidos, mensalidade e conexão WhatsApp não são lacunas de implementação básica. Ainda exigem homologação real das contas, equipamentos e fluxos utilizados por cada loja. Os testes automatizados financeiros inspecionados usam provedores simulados; não houve cobrança, estorno ou contratação nesta comparação.

## Referências e método

Referências escolhidas com o usuário: **Beefood, Anota AI, Cardápio Web, Saipos e Consumer**. São cinco referências relevantes para comparar o produto; não foi identificado um ranking independente que comprove serem os cinco maiores do Brasil.

Para próximas análises competitivas, manter estas referências, revisar a seleção quando necessário e utilizar REA para evidências de páginas, aplicativos ou artefatos públicos. Analisar o código-fonte próprio com ferramentas normais de repositório. Registrar data, fonte e limitações, distinguindo recurso anunciado, documentação, código existente e fluxo realmente testado. Reaproveitar evidências ainda pertinentes, sem repetir capturas sem propósito.

Nesta análise:

- REA abriu as cinco páginas públicas em Chromium 148.0.7778.96, aguardou 500 ms após a navegação e capturou URL, DOM e árvore de acessibilidade. Não foram acionados formulários, contas ou pagamentos.
- Os cinco cenários terminaram com sucesso e encerraram os processos de navegador criados. A completude refere-se apenas às capturas solicitadas, não aos sistemas completos.
- Foram consultadas páginas e centrais oficiais para detalhes operacionais e inspecionado o código próprio. Evidência histórica de Beefood foi reaproveitada como histórica, sem apresentá-la como captura nova do aplicativo autenticado.
- Sites comerciais e manuais demonstram o que os fornecedores anunciam/documentam. Não comprovam execução, qualidade, SLA, arquitetura privada, fornecedor exclusivo ou capacidade em escala. Nenhum backend privado foi acessado.

## O que cada referência acrescenta à comparação

| Referência | Evidência pública/documentada | Aplicação à nossa prioridade |
|---|---|---|
| Beefood | Site anuncia WhatsApp com IA, KDS, financeiro, fidelidade e pagamentos; ajuda documenta impressão e Mercado Pago. | Validar atendimento completo e impressão por setor. Não precisamos acrescentar outro gateway apenas para ter Pix/cartão. |
| Anota AI | Site anuncia atendimento por texto/áudio e recuperação de vendas; ajuda documenta início de uso e impressão setorizada. | Tornar configuração e recuperação de falhas mais simples; medir conversão antes de ampliar IA. |
| Cardápio Web | Lista automações, fidelidade, financeiro, estoque, roteirização, KDS e gestão de impressoras. | Aprofundar os módulos já existentes; mapa de entregas não equivale a roteirização otimizada. |
| Saipos | Site anuncia CMV teórico/real, financeiro e roteirização; central documenta recuperação de senha. | Melhorar autonomia do lojista e comprovar consistência dos indicadores. |
| Consumer | Site anuncia PDV, estoque/financeiro, bot, fidelidade e múltiplas impressoras; ajuda detalha configuração inicial e funcionamento local. | Criar configuração guiada, impressão resiliente e tratamento explícito de perda de internet. |

### Fontes oficiais

- Beefood: [site](https://beefood.com.br/), [pedidos pelo WhatsApp](https://ajuda.beefood.com.br/whatsapp-pedidos-chat), [impressoras](https://ajuda.beefood.com.br/impressao-cadastro-impressoras-configuracao), [marketing](https://ajuda.beefood.com.br/food-marketing), [Mercado Pago](https://ajuda.beefood.com.br/mercado-pago).
- Anota AI: [site](https://anota.ai/), [primeiros passos](https://anota.ai/ajuda/primeiros-passos/), [impressão setorizada](https://anota.ai/ajuda/impressao-setorizada/), [relatórios](https://anota.ai/ajuda/relatorios/).
- Cardápio Web: [funcionalidades](https://cardapioweb.com/funcionalidades/), [automações de WhatsApp](https://cardapioweb.com/ferramentas-automacoes-de-whatsapp/), [roteirização](https://cardapioweb.com/roteirizacao-de-entregas/), [KDS](https://cardapioweb.com/monitor-kds/).
- Saipos: [site](https://saipos.com/), [sistema para restaurante](https://saipos.com/sistema/restaurante), [como funciona](https://saipos.com/como-funciona), [recuperação de senha](https://meajuda.saipos.com/hc/pt-br/articles/34727409700628-Como-recuperar-a-senha-da-%C3%81rea-do-Cliente).
- Consumer: [site](https://consumer.com.br/), [configuração inicial](https://ajuda.programaconsumer.com.br/como-instalar-e-configurar-o-consumer-pela-primeira-vez/), [bot](https://ajuda.programaconsumer.com.br/como-utilizar-o-bot-para-whatsapp-da-consumer/), [impressoras](https://ajuda.programaconsumer.com.br/como-configurar-uma-ou-varias-impressoras-com-o-programa-consumer/), [requisitos e operação local](https://ajuda.programaconsumer.com.br/quais-especificacoes-precisa-ter-o-meu-notebook-ou-pc-para-rodar-o-consumer/).

## Lacunas confirmadas no nosso código

| Prioridade | Lacuna ou limite | Evidência própria | Resultado esperado |
|---|---|---|---|
| Alta | Recuperação de senha ainda depende do administrador. | `static/app.js:35`; comando administrativo em `app.py:1727`. | Link de recuperação com validade, uso único, limite de tentativas e revogação de sessões. |
| Alta | Configuração inicial do lojista pouco guiada. | Primeiros passos em `static/dashboard.js:345`; checklist de saúde em `business.py:254` atende o administrador da plataforma. | Checklist visível: produto, endereço, horários, entrega, pagamento, impressão e pedido de teste claramente identificado. |
| Alta | Fila de impressão está em memória e navegador não comprova saída física. | `static/printing.js:3–16`; inicialização de pedidos vistos em `static/dashboard.js:88–104`. | Pendências por aparelho, histórico, recuperação após fechar/reabrir e reimpressão consciente; depois impressão por setor com integração local apropriada. |
| Alta | Homologação real de pagamentos, mensalidade, WhatsApp e impressora não demonstrada pelos testes. | `tests/test_online_payment_browser.py`, `tests/test_billing_checkout_browser.py` usam provedores simulados; `tests/test_printing_browser.py` substitui `window.print` e gera PDF. | Piloto autorizado com conta do lojista, confirmação do pagamento, pedido e comprovante; reconexão de WhatsApp e testes físicos de impressão. |
| Alta | Saúde operacional e recuperação precisam de comprovação mais ampla. | `/health` em `app.py:514–517` verifica banco; `inbox_service.py:126–134` contém heartbeat. `scripts/backup.py` cobre SQLite. | Alertas de fila atrasada, falha de integração e pagamentos incertos; exercício documentado de restauração PostgreSQL e teste de carga representativo. |
| Média | Não há visão completa de repasses e dinheiro efetivamente disponível. | `online_payments.py:29–35` registra valor, estorno, taxa e status; `:135–165` já confere taxas reais. | Exibir bruto, taxas, estornos, líquido, previsão/liberação e divergências. Não chamar a conciliação básica já existente de ausente. |
| Média | Verificação de e-mail e segundo fator não implementados nos fluxos inspecionados. | `app.py:624–664`; campos de autenticação em `schema.sql:2–5`. | Confirmação do endereço e proteção adicional para ações administrativas sensíveis. Hash e limitação de tentativas já existem. |
| Média | Rede pública de lojas não equivale a gestão consolidada de filiais. | `schema.sql:16` limita proprietário a uma loja; `store_network.py:31–121` oferece rede pública e convites. | Administração de múltiplas unidades, permissões e indicadores consolidados quando houver demanda. |
| Média | PDV sem operação offline completa. | `static/sw.js:1–21` trata push/notificações; checkout em `static/operations.js:52–58` depende do servidor. | Primeiro avisar perda de conexão e preservar rascunhos; posteriormente sincronização de vendas com proteção contra duplicidade. |

O código não permite concluir se há monitoramento externo ou backups do provedor configurados. Essas configurações devem ser verificadas antes de afirmar que estão ausentes. Não foi executado teste de carga nesta análise.

## O que já existe e deve ser aprofundado

- **Pagamentos:** Pix/cartão via Mercado Pago, tentativas e confirmação no servidor, taxas, estorno autorizado e mensalidade. Falta evidência de operação financeira real neste trabalho, não o módulo inteiro.
- **WhatsApp:** conexão, atendimento, mídia, busca, passagem ao humano e pedido guiado em `connectors.py`, `inbox.py`, `inbox_media.py`, `chat_orders.py`. Disponibilidade concreta depende da conexão de cada loja. A qualidade da IA/OpenRouter não foi homologada aqui.
- **Operação:** PDV, caixa, mesas, cozinha, estoque/fichas, relatórios e entregas já possuem implementação. Contar itens de menu não comprova equivalência operacional com outro produto.
- **Marketing:** segmentação, campanhas, fidelidade/cashback e sugestões já têm módulos. A evolução deve medir retorno, consentimento, entrega e recuperação de vendas; não apresentar tudo como funcionalidade ausente.

## Ordem recomendada

1. Recuperação de senha e configuração guiada: reduzir reclamações e dependência de suporte.
2. Impressão com pendências recuperáveis e diagnóstico claro; validar modelos físicos antes de prometer compatibilidade.
3. Piloto completo de Pix, cartão, mensalidade e WhatsApp, com escopo financeiro explicitamente autorizado.
4. Alertas de operação, restauração comprovada e avaliação de carga.
5. Visão de recebíveis; depois aprofundar roteirização, produtividade da cozinha, retenção e filiais conforme uso real.

Fiscal, marketplaces, TEF/maquininhas e novos fornecedores continuam para depois, conforme orientação do usuário. Impressão comum de pedido não é emissão de NFC-e/NF-e. Não há base para prometer suporte universal a toda impressora ou equivalência total aos cinco produtos.

## Registro REA

Bundle local: `work/beefood-audit/mercado-cinco-rea-2026-10-22.json`, com cinco registros. Os IDs abaixo identificam as observações; SHA-256 identifica o DOM capturado, não o produto completo.

| Alvo e URL final | Evidence ID | SHA-256 DOM |
|---|---|---|
| Beefood — https://beefood.com.br/ | `ev_4a6377be060d1f97de4bf7bc464869c9bcbfe8236dcc8ef2e56f777c9ca58bfb` | `a59c07f8f468bd2bc8893aec1a910868832a80924e33f1ac87db485e1de50053` |
| Anota AI — https://anota.ai/ | `ev_87385728d08740e3ea46bed51e107885fa85939ad67a6b3ad9687409a6314c7c` | `527e3d43aebba17286aa499d0ad072809d88ae29563719e474c6351751990cd4` |
| Cardápio Web — https://cardapioweb.com/funcionalidades/ | `ev_fb4f0612bd89de3d7a3869be08de80f2af4c4475264e37a29fb8665fa0c86a21` | `219cc34a32c8d190ce1e12e0911630afae060fb4163ff6df6a116765c6380eb3` |
| Saipos — https://saipos.com/ | `ev_9ff4f420a6cf42a6f1f2519b029b90ac57e9f6b2b1c6c4752b72d61599e0aa63` | `99af913a5f73145950f095d4cddeef82b7fc7a9d0e209ee39ca7d8507afdacc9` |
| Consumer — https://consumer.com.br/ | `ev_01caf5a5b1d8e77ddd070d5b07a3391669cedda452917b77fe1b7b5012fd4bff` | `95818e65359a16a9578c3472d707ed80872cfef349e6a7c5bd49e9756e0ab9d6` |

Limites: apenas páginas públicas abertas, sem navegação nos painéis autenticados, sem gravação de corpos de rede, sem teste de aplicativos locais ou equipamentos. Menus ocultos, carregamentos posteriores e execução das funções anunciadas ficaram fora do cenário. Nenhuma inferência sobre o código privado dos concorrentes foi tratada como fato.
