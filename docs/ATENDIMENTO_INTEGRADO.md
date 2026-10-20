# Atendimento integrado — 20/10/2026

A loja conecta seu número pelo QR Code em Atendimento WhatsApp. A tela verifica a conexão a cada quatro segundos enquanto a janela de vínculo está aberta. Fechar a janela ou sair do atendimento interrompe essa verificação. Ler o código não libera o envio: a autorização do dono continua separada. O aplicativo usa sua interface própria e o conector Evolution já existente.

## Conversa, cliente e pedido

Em telas largas, a lista de conversas, o chat e os pedidos do cliente ficam lado a lado. Em telas menores, o botão **Cliente e pedidos** abre o contexto abaixo da conversa. O histórico considera somente pedidos da mesma loja e do mesmo número normalizado; não agrega dados de outras lojas.

O painel mostra até oito pedidos recentes, suas situações, itens, adicionais, pagamento e destino. A contagem de compras exclui cancelamentos e o total comprado soma somente pedidos concluídos. **Usar cliente e endereço em novo pedido** preenche uma nova montagem, sem repetir produtos ou criar uma venda automaticamente. O atendente deve confirmar o endereço e os itens atuais. A criação usa a rota manual existente, com conferência de preços/estoque e idempotência; não envia mensagem ou comprovante pelo WhatsApp automaticamente.

A busca dentro da conversa filtra **as mensagens já carregadas** (texto e nome do anexo). Carregar mensagens anteriores amplia esse conjunto. Não promete importação de todo o histórico do celular nem pesquisa fora da conversa.

## Fotos e áudios

Fotos e áudios recebidos após a conexão aparecem na conversa e chamam atendimento humano. O atendente pode abrir a foto ou ouvir o áudio sem sair do painel. A disponibilidade de mídias recebidas depende de o serviço de conexão ainda ter o arquivo. Mensagens temporárias ou de visualização única não são recuperadas por esta implementação.

**Anexar foto ou áudio** permite selecionar arquivo e revisar antes de confirmar. É necessário assumir a conversa, ter envio autorizado e conexão confirmada. A interface não grava o microfone. Fotos aceitam legenda; áudios são enviados sem legenda, com texto em mensagem separada.

- Limite de 4 MiB por arquivo. Imagens: PNG, JPEG ou WebP; são reprocessadas para WebP, reduzidas e têm metadados removidos. Áudios: OGG, MP3, WAV, M4A ou WebM com assinatura compatível.
- Arquivos saem pela mesma fila idempotente do texto. Resposta incerta exige conferência, sem repetição automática. O comprovante do conector não é uma confirmação de leitura pelo destinatário.
- Os bytes de anexos enviados ficam na coluna privada `inbox_messages.media_data`; os metadados ficam em `media`. O polling do histórico não lê nem expõe base64. Não há URL pública de anexo, credencial ou URL remota repassada ao navegador.
- O endpoint de arquivo exige sessão e loja correta, usa `no-store` e suporta Range para áudio. Recuperação no conector usa apenas a identificação da mensagem, com resposta limitada e sem redirecionar credenciais.
- Anexos finalizados (enviados/cancelados) perdem os bytes sete dias após a finalização enquanto o dispatcher está ativo; texto e metadados permanecem. Pendentes e incertos exigem revisão e contam no limite inicial de 48 MiB codificados por loja. Exclusão da conversa e anonimização apagam também os anexos locais. Isso não apaga arquivos que já saíram ao WhatsApp.

## Publicação e evidência

Adicionar antes do deploy, no schema privado `seucomercio`, duas colunas TEXT NOT NULL DEFAULT '': `media` e `media_data` em `inbox_messages`. A migração local em `migrations.py` contém a mesma adição para SQLite/PostgreSQL. Não alterar grants ou expor a tabela via API pública.

Teste de navegador cobre vínculo com serviço local de contrato, abertura do contexto, criação de pedido, recepção de foto, envio de foto e áudio, busca e layout móvel. Testes de backend verificam sessão, isolamento de loja, filas, duplicatas, retenção e transporte HTTP. São dados e provedores de teste; um piloto com número real ainda precisa validar a operação e os formatos disponíveis no conector instalado.

REA reutilizou e validou o registro do bundle Beefood anteriormente coletado. Foram observados QR Code e painel BeeBot em iframe próprio, sem comprovar WhatsApp Web oficial embutido. Evidências: resumo `ev_1e9dc6b96c274f3559e07b982360b43cdbee66adba2a985c8ebefd417934d3e1`; rota `ev_04a502a5fa1d0d5eb98def42544a04d5d37b71a94e66722a3525f287c9d1ec9c`. A cobertura é parcial (análise original limitada por tempo), sem acesso ao backend ou execução autenticada do concorrente. A interface, as regras e as proteções desta entrega são implementação própria.

Referências: [vínculo no Anota AI](https://anota.ai/ajuda/primeiros-passos/), [atendimento BeeBot](https://ajuda.beefood.com.br/whatsapp-atendimento-beebot).
