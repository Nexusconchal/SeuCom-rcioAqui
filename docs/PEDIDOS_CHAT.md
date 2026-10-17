# Pedidos guiados pelo WhatsApp e consulta ao catálogo

## Ativação

Em Atendimento WhatsApp → Respostas e atalhos, o dono/gerente pode habilitar **Pedido guiado pelo WhatsApp**. O dono também precisa ter conectado o número, ativado conversas, autorizado envios e ligado o bot. A publicação mantém a função desativada em todas as lojas que não a escolheram explicitamente. Não conecta números nem envia mensagens para clientes como teste.

O cliente escreve FAZER PEDIDO. O fluxo permite pesquisar produtos, escolher grupos obrigatórios e adicionais, informar quantidades e observações, adicionar/remover itens, anotar cupom, escolher entrega/retirada, bairro ou CEP, endereço, pagamento e troco. O resumo mostra itens, opções, observações, pagamento, troco e os valores calculados pelo servidor; somente CONFIRMAR enfileira a criação. Resumos extensos demais pedem redução da sacola ou conclusão pelo cardápio/atendente, sem cortar o total ou aceitar confirmação parcial. AJUDA mostra a etapa, VOLTAR retorna à sacola, CANCELAR desiste da montagem e ATENDENTE/HUMANO passa para a equipe. Um pedido já criado exige tratamento normal de alteração/cancelamento; cancelar a montagem não cancela uma venda existente.

## Consistência

- Cardápio, disponibilidade, receita, opções e preços são lidos dos mesmos serviços do site. Não há catálogo paralelo de preços.
- O orçamento e a criação foram extraídos dos handlers existentes para funções internas comuns. As rotas públicas continuam com suas proteções de sessão/CSRF/limites. A criação de chat possui verificação adicional dentro da transação: loja, conversa, responsável, autorização, bot, função habilitada e chave da montagem.
- `delivery_tick` processa confirmações antes de enviar as respostas. A reivindicação é persistente; nenhuma chamada HTTP é feita dentro da transação de reivindicação. Cada confirmação mantém chave/payload imutáveis. Se o processo cair depois do commit, recuperar a tentativa devolve o pedido existente sem baixar estoque novamente.
- Antes da primeira criação, o servidor revalida estoque, opções, condições da loja e total esperado. Mudança de total exige uma nova montagem/confirmação; não há cobrança silenciosa de um valor novo. Confirmações não executadas em cinco minutos expiram. Uma operação que já concluiu o commit pode ser recuperada pela mesma chave.
- Assumir/transferir/encerrar a conversa, chamar humano ou apagar a montagem impede criação futura. Uma operação já concluída permanece um pedido normal. O comprovante de criação (`automated=2`) pode sair depois da passagem para humano; continua sujeito à autorização de envio e fica retido após 24 horas sem tentativa. Pausar/desconectar retém comprovantes pendentes para revisão, sem liberação automática. Pausar envio/desligar o bot também impede novas criações. O resumo de estado da montagem aparece no painel sem expor seu payload pela API de conversas.
- Pedido recebe origem `whatsapp`; Pix manual permanece manual, cartão é na entrega/retirada e Pix online usa a integração existente quando disponível. A IA não cria pedidos, escolhe forma de pagamento nem confirma recebimento.

## Dados e limites

Montagens ficam em chaves privadas `inbox.cart.<loja>.<conversa>` da tabela `platform_settings` existente, sem nova migração/RLS/grants. Dados incluem itens, opções, observações, endereço e a confirmação necessária. Montagens expiram em 24 horas; limpeza ocorre em até cinco minutos após a expiração enquanto o serviço está ativo. Exclusão da conversa ou anonimização do cliente apaga a montagem imediatamente. Confirmações em recuperação precisam ser resolvidas antes de limpar seus dados. A exclusão não envia nada ao provedor.

Até 20 linhas por montagem, 50 unidades por linha, oito produtos por página e até 30 opções visíveis em um grupo. Quantidades de opções respeitam o cadastro. Mídias chamam atendimento humano. O fluxo guiado desta versão é para pedidos imediatos, sem agendamento, pagamento com saldo da carteira ou fiado pelo chat. Recursos mais específicos continuam disponíveis no cardápio/painel. Nenhum pedido real foi criado como verificação desta entrega.

O processamento depende da aplicação/worker em execução. Não transforma Render Free em hospedagem sempre ativa. O bloqueio transacional do adaptador PostgreSQL não foi redesenhado nesta mudança; não há alegação de capacidade nacional comprovada.

## OpenRouter gratuito: consulta assistida

A opção **Usar IA gratuita na consulta de produtos** habilita um auxiliar para o atendente. Em uma conversa, **Consultar catálogo** permite escrever uma dúvida sobre produtos/ingredientes. O resultado pode ser inserido no rascunho; exige revisão e envio humano. Não é um bot generativo autônomo conversando com consumidores.

O servidor lê `OPENROUTER_API_KEY`. Sem chave, com a opção desligada, fora da cota ou em caso de erro, mantém a busca local. Não coloque a chave no JavaScript, no repositório ou em mensagens de suporte. Nenhuma chave foi criada, contratada ou ativada por esta entrega.

Requisição fixa ao endpoint oficial `https://openrouter.ai/api/v1/chat/completions`, modelo **openrouter/free**, sem lista de fallback pago, ferramentas ou execução de ações. Resposta limitada a intenção e IDs de produtos; IDs externos ou respostas inválidas são recusados. Descrições e preços da resposta vêm do cadastro atual, não de texto livre do modelo. Há limite de resposta HTTP de 64 KiB, timeout de 12 segundos, proibição de redirecionamento com credenciais e orçamento inicial transacional de 10 consultas/loja/dia e 40/plataforma/dia (UTC). A contagem é reservada antes de chamar e inclui erros, conservadoramente.

Só seguem a pergunta escrita pelo atendente e nomes/descrições públicas de até 80 produtos disponíveis. O aplicativo não anexa nome/telefone do cliente, histórico da conversa, endereços ou credenciais da loja. O texto escrito pelo atendente deve conter somente a dúvida de produto. A entrada recusa padrões de contatos/endereços; o atendente deve usar apenas a dúvida de produto. Não há promessa de disponibilidade, capacidade nacional ou uso ilimitado de IA grátis. Não presume ausência de alergênicos a partir do resultado; a revisão usa os ingredientes cadastrados.

Referências: [roteador gratuito](https://openrouter.ai/docs/guides/routing/routers/free-router), [limites](https://openrouter.ai/docs/api/reference/limits) e [saída estruturada](https://openrouter.ai/docs/guides/features/structured-outputs). As cotas do fornecedor podem mudar; o fallback local mantém o atendimento.

## Verificação e pendências

Testes cobrem criação única, estoque/adicionais, preço alterado, fechamento da loja, expiração, opções obrigatórias, bairro, troco, concorrência, interrupção após commit, passagem para humano entre reivindicação e transação, exclusão de dados, autorização e limites da IA. O navegador percorre configuração → callbacks autenticados → HTTP Evolution local → pedido real em banco de teste → painel, e consulta OpenRouter controlada → rascunho sem envio. Provedores e clientes são fictícios.

A falha intermitente antiga do teste de checkout com combinações não se repetiu em cinco execuções locais. O teste agora verifica o HTTP de criação e mostra a resposta da API, em vez de apenas esperar navegação. Sua causa original permanece não determinada; isso não deve ser apresentado como correção comprovada daquela falha.

Ainda são necessários chave/ativação voluntária, piloto autorizado com número real e impressora, teste de restauração e carga em infraestrutura definida. Fiscal, marketplaces, TEF e novos fornecedores continuam fora desta entrega.
