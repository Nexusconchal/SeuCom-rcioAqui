# Página inicial

A proposta aprovada foi implementada em HTML e CSS, com o cardápio no celular ao lado de uma representação do painel. A composição é identificada como exemplo demonstrativo. Não usa a imagem gerada como interface, nem apresenta números de clientes, resultados ou depoimentos fictícios.

`static/landing.js` renderiza apenas a página inicial. Seus estilos ficam sob `.landing-page` em `static/landing.css`, preservando o cardápio e as áreas autenticadas. O acesso passa pelo bootstrap de sessão existente: visitantes seguem para cadastro quando permitido; usuários autenticados seguem para o painel; instalações com cadastro desativado mostram entrada na conta.

## Demonstração

O visitante escolhe de um a cinco burgers de exemplo, confirma o pedido simulado e avança o preparo. Todo o estado fica na memória da página. A simulação não chama endpoints de pedido, pagamento, WhatsApp ou caixa, e não grava dados no navegador. Recomeçar ou recarregar limpa a simulação. Preços e pedidos da composição são ilustrativos.

As condições de assinatura permanecem na área Seu plano, usando os valores reais da loja. A página pública não fixa preços nem promete teste ou integrações que dependem de configuração.

## Imagem

`static/landing-burger.webp` é uma versão local de 650 px da fotografia que a página inicial já utilizava no Unsplash: <https://images.unsplash.com/photo-1568901346375-23c9450c58cd>. O arquivo tem aproximadamente 56 KiB e elimina a dependência de carregamento externo da foto na página inicial. O logotipo existente foi preservado.

## Verificação

Verificação local em Chromium: larguras de 320, 390, 768, 1440 e 1920 px sem rolagem horizontal; imagens locais carregadas; simulação completa, quantidade, reinício e FAQ; nenhuma requisição de escrita ao usar a demonstração. Cadastro, login e entrada no painel autenticado foram percorridos com uma conta fictícia em banco local. Também foi conferida a entrada com cadastro desativado. Capturas de tela foram inspecionadas em computador e celular.
