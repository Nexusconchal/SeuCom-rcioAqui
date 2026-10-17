# Atendimento WhatsApp

## Ativação por loja

1. Em **Atendimento WhatsApp**, conecte o número pelo QR ou confira a conexão existente.
2. **Ativar conversas** registra o endereço de recebimento com segredo individual. O painel distingue número conectado, recebimento, autorização de envio e processamento.
3. O dono escolhe **Autorizar envio**. Isso permite novas respostas desta loja; não agenda campanhas. Respostas antigas sem tentativa ficam para revisão e antigas respostas do bot são canceladas.
4. Opcionalmente, ligue o bot e personalize **Respostas e atalhos**. Há uma simulação interna que não chama o serviço de envio.

Não há conexão ou autorização automática de lojas durante a publicação. Ter credenciais de serviço no servidor não significa que o número esteja conectado.

## Conversas e equipe

- Busca por nome, telefone ou última mensagem; filtros para abertas, não lidas, aguardando atendente, minhas, encerradas e todas. A lista reúne até 200 conversas recentes.
- Atualização a cada cinco segundos enquanto a aba está visível. O painel preserva rascunhos e posição de leitura. O histórico carrega 100 mensagens por consulta e permite abrir anteriores.
- Assumir pausa o bot e cancela respostas automáticas ainda na fila. Dono e gerente podem transferir para um atendente ativo da mesma loja. Caixa atende suas conversas, mas não configura conexões, bot ou envio.
- Atalhos `/cardapio`, `/entrega`, `/aguarde` e os cadastrados inserem texto para revisão. Não enviam ao serem selecionados. Ctrl+Enter confirma o envio quando o botão está disponível.
- **Montar pedido** abre o fluxo existente de balcão com nome e telefone preenchidos. O atendente escolhe os itens e confirma. Preço, complementos, estoque e idempotência continuam conferidos pelo servidor.
- Texto que solicita ATENDENTE/HUMANO, mensagem de mídia ou texto sem regra correspondente pede atendimento humano. Mídias devem ser abertas no WhatsApp; não há transcrição de áudio nesta versão.

## Bot e mensagens

Até 12 regras, dez palavras/expressões por regra e 20 atalhos. Correspondência normalizada de acentos, caixa e pontuação, com limites de palavra. Saudações, cardápio, horário, entrega/pedido mínimo e Pix têm respostas iniciais. Há texto específico de loja fechada, usando a situação real da loja. Um intervalo de três segundos limita respostas automáticas sucessivas.

Variáveis permitidas: `{nome}`, `{loja}`, `{link}`, `{horario}`, `{pix}`, `{entrega}`, `{minimo}`. O editor valida estrutura, tipos, comprimentos e identificadores. As preferências ficam na tabela privada existente `platform_settings`, em chaves prefixadas e derivadas da loja autenticada; não há nova tabela, exposição na Data API ou migração de esquema.

Além das regras e do pedido assistido, há uma opção separada de [pedido guiado no chat](PEDIDOS_CHAT.md), desligada por padrão, com confirmação e validação do servidor. A consulta opcional de catálogo com OpenRouter ajuda o atendente a preparar uma resposta; não envia texto gerado nem cria pedidos automaticamente por IA.

## Processamento da fila

`INBOX_DISPATCH_MODE=embedded` é o padrão. Um loop por processo da aplicação web começa na primeira requisição, sem criar um recurso de hospedagem. Lê apenas lojas com autorização explícita em `inbox.sending.<id>`. O modo `external` desliga o loop web para usar `marketing_worker.py`; `off` também desliga o loop web. O worker externo continua sendo responsável pelas campanhas agendadas: o loop embutido envia apenas atendimento.

Cada tentativa é reivindicada em transação antes do HTTP, com alteração condicional de estado; SQLite serializa escrita e o adaptador PostgreSQL usa o bloqueio transacional já existente. O envio ocorre fora da transação. Um resultado HTTP 200/201 significa **aceite pelo serviço**, sem comprovar entrega ou leitura no aparelho do cliente.

- `queued`: aguardando tentativa; `processing`: tentativa em andamento.
- `sent`: serviço aceitou a requisição; a interface mostra **Aceita pelo serviço**.
- `uncertain`: sem confirmação, inclusive tentativa interrompida há mais de cinco minutos. Não é reenviada automaticamente.
- `held`: resposta humana sem tentativa aguardando revisão. Inclui mensagens anteriores à ativação e respostas pendentes há mais de 24 horas. O atendente assume a conversa e pode recolocá-la na fila explicitamente, preservando a data original.
- `cancelled`: pendência cancelada; respostas do bot com mais de cinco minutos também expiram para evitar respostas fora de contexto.

Pausar ou desconectar segura respostas humanas ainda não iniciadas e cancela automáticas. Uma operação já em processamento pode concluir. O hook do Gunicorn sinaliza parada e espera a requisição corrente; o worker externo usa SIGTERM/SIGINT. O heartbeat interno alimenta o indicador de processamento e não contém mensagens, telefones ou credenciais.

O loop depende de o serviço estar executando. Render Free pode suspender a aplicação; não se promete operação contínua em serviço que adormece. Para essa exigência, é necessário hospedagem sempre ativa ou worker dedicado autorizado. Nenhum serviço pago foi contratado nesta alteração.

## Referências e validação

Recursos de referência: [atendimento BeeBot](https://ajuda.beefood.com.br/whatsapp-atendimento-beebot), [respostas configuráveis BeeFood](https://ajuda.beefood.com.br/whatsapp-respostas) e [atendente Anota AI](https://anota.ai/home/funcionalidade/atendente-virtual/). Não há acesso ao backend privado desses concorrentes nem afirmação de paridade integral.

A consulta pública do serviço Evolution existente respondeu versão **2.3.7**. O contrato de webhook foi conferido no [DTO dessa versão](https://github.com/evolution-foundation/evolution-api/blob/2.3.7/src/api/integrations/event/event.dto.ts) e no [controlador](https://github.com/evolution-foundation/evolution-api/blob/2.3.7/src/api/integrations/event/webhook/webhook.controller.ts): objeto `webhook`, eventos, `byEvents`, `base64` e headers customizados. O aplicativo verifica o segredo do callback, a instância, origem individual, tipo de payload e duplicidade do ID. Não persiste o corpo bruto do provedor nem a chave que pode acompanhá-lo.

Testes cobrem fila opt-in, pendências antigas, concorrência, retomada explícita, preferências por loja, permissões, handoff, paginação e parada do loop. O teste de navegador utiliza um servidor HTTP local compatível com o contrato Evolution: configura callback, injeta recebimento, processa bot/resposta humana e observa atualização do painel sem perder rascunho. Isso não substitui um piloto com o número conectado e uma conversa real autorizada.
