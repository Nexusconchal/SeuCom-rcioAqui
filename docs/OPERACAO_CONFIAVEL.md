# Operação confiável — 22/10/2026

Implementação das seis prioridades da comparação de mercado: autonomia de acesso, configuração guiada, pendências de impressão, homologação dos fluxos, recebíveis e diagnóstico/recuperação. As referências e evidências REA estão em `COMPARACAO_MERCADO_2026-10-22.md`; não houve nova investigação de código privado nem contratação de fornecedores nesta entrega.

## Acesso e recuperação de senha

`/entrar` oferece **Esqueci minha senha**. O link usa fragmento, que não é enviado em URLs HTTP, e sai da barra de endereço quando lido. Somente seu hash fica no banco privado `account_tokens`. Validade de 30 minutos, uma utilização, limite de tentativas por IP e intervalo mínimo de dois minutos por conta. A resposta não revela se o e-mail existe. A troca incrementa `auth_version` e revoga todas as sessões e links anteriores; o usuário entra novamente com a nova senha. Não há autenticação automática pelo link.

Como o proprietário informou não ter serviço de e-mail, o envio **não foi ativado**. Sem configuração, a interface informa isso e mantém a recuperação administrativa disponível no servidor.

Para ativar via HTTPS:

1. Configurar um remetente/domínio verificado no Resend e uma chave com permissão de envio. Nenhuma conta foi criada automaticamente.
2. Salvar `RECOVERY_EMAIL_PROVIDER=resend`, `RESEND_API_KEY` e `MAIL_FROM` no ambiente seguro do Render. Manter `PUBLIC_URL` com a origem HTTPS correta. Não colocar chaves em código, navegador ou conversa.
3. Publicar as variáveis, solicitar recuperação na própria conta e verificar entrega e troca da senha.

SMTP com TLS é alternativa para hospedagens que o permitam: `RECOVERY_EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT` 465/587, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`. O Render Free bloqueia essas portas; não usar SMTP nesse plano. Fontes: [Render Free](https://render.com/docs/free), [API de envio do Resend](https://resend.com/docs/api-reference/emails/send-email), [OWASP — recuperação de senha](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

O envio é assíncrono para que a latência do e-mail não revele contas cadastradas. Se o processo parar antes do envio, o usuário pode solicitar novo link após o intervalo. Falhas são registradas sem destinatário, token ou corpo do provedor; a Central do Dono apresenta a falha de envio.

## Configuração guiada e simulação

Na Visão geral, **Prepare sua loja para vender** acompanha sete etapas: produto, contato/endereço, horários, entrega, pagamentos, impressão e conferência do pedido. Dados verificáveis são calculados do cadastro. Etapas que dependem da equipe são identificadas como conferências manuais, registradas por loja com usuário e horário. O checklist começa recolhido nas lojas que já possuem pedidos; sua abertura fica salva por loja e usuário.

No PDV, ao finalizar a sacola, **Simular valores sem criar pedido** utiliza a cotação do servidor. Calcula produtos, descontos, entrega e total, sem reservar estoque, criar venda ou cobrança. **Criar pedido** continua sendo a ação que confirma a venda.

## Impressão

O módulo mantém papel, fonte, área útil, via de motoboy e setor por aparelho. Pedidos impressos ganham histórico separado por loja e usuário no mesmo navegador. A fila guarda apenas identificadores, via, estado e tentativas; não guarda nome, telefone, endereço nem HTML do cliente. Na recuperação, o pedido é buscado novamente no servidor, com autorização e isolamento por loja.

- O fechamento da janela resulta em **Confira se saiu no papel**, nunca em confirmação física automática.
- **Conferi no papel** e **Dispensar** registram decisões da equipe. Reimpressão é explícita.
- Reabrir o painel recupera pendências sem reenviar tudo automaticamente. Pedidos novos elegíveis, inclusive pagamentos online que acabaram de ser confirmados, entram no fluxo automático se ativado.
- Pedidos online aguardando pagamento não são enviados automaticamente para impressão de produção.
- Chrome/Edge usam Web Locks para impedir disparos automáticos duplicados entre abas do mesmo navegador. Não há promessa de sincronização de impressão entre computadores ou perfis diferentes.
- Armazenamento inválido/indisponível bloqueia a impressão rastreada e exibe orientação; não há descarte silencioso de pendências quando o limite de 500 registros é atingido. Registros concluídos expiram após 30 dias. O histórico exibe primeiro as pendências, até 100 registros por vez.
- Limpar dados do navegador remove o histórico local. Uma integração nativa com spooler/equipamento continua sendo uma evolução independente.

O navegador não confirma papel, guilhotina ou gaveta. Drivers e equipamentos precisam de teste físico. Impressão de pedido não emite NFC-e/NF-e.

## Recebíveis online

**Recebíveis online** separa bruto, taxas, estornos/contestações, líquido informado e liberação no Mercado Pago. Campos opcionais são coletados somente da consulta autenticada e verificada ao provedor: `transaction_details.net_received_amount`, `money_release_date`, `money_release_status`. Valores ausentes ou inválidos não impedem confirmar o pagamento e não são inventados como saldo disponível.

**Liberado** significa disponibilidade na conta do provedor, não transferência para banco. Estornos parciais, dados ausentes e situações não reconhecidas ficam fora dos saldos classificados e exigem conferência. O período filtra a última atualização; totais usam todas as transações do período, e a tabela tem limite explicitamente indicado. A mensalidade da plataforma é separada dos pagamentos dos pedidos.

O botão por pedido consulta novamente o Mercado Pago, sem criar cobrança ou estorno. A página não substitui o extrato e as informações finais do provedor. Fonte: [consulta de pagamentos](https://www.mercadopago.com.br/developers/pt/reference/online-payments/checkout-api-payments/get-payment/get).

## Diagnóstico e alertas

- No painel do lojista: filas atrasadas, mensagens incertas, pagamentos e estornos para conferir, campanhas aguardando envio. Avisos aparecem na operação para dono/gerente.
- Na Central do Dono: os mesmos indicadores agregados, configuração de e-mail, heartbeat do atendimento, amostra de requisições deste processo e último exercício de restauração registrado.
- `/health` continua simples e rápido para a disponibilidade do banco. Alertas de integrações não derrubam a instância saudável do site.
- As respostas têm `X-Request-ID`; requisições lentas ou com erro geram log com endpoint, status, duração e identificador, sem corpo, query string, contatos ou credenciais.
- `flask --app app operations-check` oferece JSON de leitura para um monitor externo e retorna código 1 quando há alertas. Nenhum monitor externo pago ou rotina de notificação foi contratado/configurado nesta entrega.
- Perda de internet ou falha de servidor produz aviso no painel. Isto não implementa PDV offline completo.

Os diagnósticos não são um atestado de homologação de pagamentos, WhatsApp ou impressoras. Uma fila vazia, sozinha, não prova que um provedor esteja conectado.

## Backup e exercício de restauração PostgreSQL

`scripts/backup.py` continua atendendo SQLite. Para PostgreSQL, `scripts/postgres_backup.py` usa ferramentas oficiais `pg_dump`/`pg_restore` compatíveis com a versão do servidor. O dump usa um snapshot exportado em transação somente leitura; a contagem das tabelas é feita no mesmo snapshot. O arquivo não sobrescreve destinos existentes. Um manifesto registra tamanho, SHA-256, data e contagens. Credenciais passam pelo ambiente dos subprocessos e não são impressas.

Exemplo com credenciais já definidas no ambiente seguro:

```powershell
python scripts/postgres_backup.py backups/loja-2026-10-22.dump
```

Para um exercício, fornecer `RESTORE_TEST_DATABASE_URL` apontando para **outro banco vazio**, com nome iniciado por `restore_` e diferente do banco de origem:

```powershell
python scripts/postgres_backup.py backups/exercicio-2026-10-22.dump --restore-test --record-success
```

O script restaura em transação única, confere tabelas e contagens e só então registra o sucesso na origem. Nunca usa `--clean`, apaga tabelas ou restaura sobre o banco de origem. A proteção recusa nomes de banco iguais mesmo em hosts diferentes. O CI Linux usa opcionalmente `--docker-image postgres:17` para ferramentas compatíveis e um banco de teste descartável criado especificamente pelo teste. Não é uma restauração de produção.

Guardar dumps fora do diretório público/repositório, com acesso restrito e criptografia no armazenamento escolhido. Não enviar dumps em chat. O dump pode conter dados pessoais e credenciais já criptografadas da aplicação. Ele não inclui objetos do Storage, uploads externos, configurações/secrets do Render ou papéis globais do PostgreSQL. Recuperação completa requer preservar esses componentes e `SECRET_KEY` separadamente. A política de retenção e o backup real da hospedagem precisam ser configurados pelo proprietário; nenhum serviço de backup foi comprado.

O exercício comprova restauração lógica de dados de teste e contagens. Não comprova recuperação de todos os serviços em produção ou um SLA de recuperação. Fonte: [pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html).

## Homologação antes de operar com clientes

Os testes automatizados cobrem navegador, API, banco, autorização, uso concorrente do link, cotação sem venda, recuperação das pendências, falhas de pagamento simuladas e isolamento entre lojas. As simulações financeiras não são transações reais.

Continuam dependentes de acesso/equipamentos externos:

1. Recuperar a própria conta por e-mail real depois de configurar o remetente.
2. Na conta do lojista, confirmar um Pix e um cartão autorizados, verificar o pedido, taxas, liberação e cancelamento/estorno quando realmente necessário.
3. Validar a mensalidade separadamente, sem confundir pagamento do pedido com assinatura da plataforma.
4. Conectar WhatsApp da loja, receber uma mensagem de teste autorizada, testar reconexão e passagem ao atendente.
5. No Windows, imprimir nas térmicas utilizadas, conferir acentos, tamanho, via de entrega, setor, reabertura do painel e falta de papel.
6. Configurar e exercitar backup real com Storage e secrets preservados, em destino de recuperação separado.

Não foram criados pagamentos, estornos, assinaturas ou envios reais de WhatsApp/e-mail para concluir esta entrega. Fiscal, marketplaces, TEF, filiais e PDV offline completo permanecem para etapas próprias, fora das seis prioridades desta implementação.
