# Comparação técnica com BeeFood — 15/10/2026

Esta revisão atualiza as comparações anteriores. Examina o aplicativo web publicado, não apenas o site comercial. Não houve login no BeeFood, acesso a lojas de terceiros ou execução de instaladores. O código privado dos servidores e o resultado físico dos equipamentos continuam desconhecidos. Ter uma função no frontend não comprova que uma integração esteja contratada ou operando.

## Evidência e limites

- Página do aplicativo: https://beefood.app/ . HTML coletado: 5.951 bytes; SHA-256 `d4ab3a8c2b3626eeafa0acb837023f0abb7ef2ad80bd362af8dfe414b0eb94e7`.
- JavaScript entregue pelo próprio aplicativo: https://beefood.app/assets/index-HwxeXkGn.js . 10.803.572 bytes; SHA-256 `8822fd073851d9b0f44b0452f55f6fae85d16a4feec2214caf4d2390ca77a099`.
- REA 6.5.0, adquirido do registro npm com integridade SHA-512 conferida, executado pela CLI pública. A configuração do Codex não foi alterada. O MCP não passou a estar conectado por isso.
- A primeira execução encontrou restrição de acesso do Windows. A execução autorizada fora dessa restrição leu o JavaScript como texto inerte. Preservou análise parcial, identificação `ev_d4f94348b43dc20f8220c9f5a4bbf91ebcb95e377185b350be1da68611cdaba4`: 1 arquivo JavaScript analisado, 2.588.411 nós de sintaxe visitados, 788 achados, grafo com 233 nós/796 relações. O limite de 180 segundos interrompeu a análise completa; 3 arquivos inventariados não foram selecionados. Esses números medem análise estática, não funções testadas ou falhas encontradas.
- O grafo parcial não reconstrói todos os serviços nem prova execução. As verificações focadas abaixo também usaram busca textual no arquivo original; seus deslocamentos são índices de caracteres Unicode, não bytes.
- Não foram invocados endpoints privados, credenciais encontradas em arquivos ou serviços locais do concorrente. Nenhuma informação de clientes foi consultada. O instalador Windows vinculado pelo frontend foi identificado por HEAD (286.118.313 bytes), sem download ou execução.

## O que o código público mostrou

| Evidência estática | Localização aproximada no JavaScript coletado | Interpretação permitida |
| --- | --- | --- |
| Configuração de serviço de impressão local, porta 1316; serviços separados para balança, TEF e cozinha | caracteres 221.800–222.500 | A operação com periféricos depende de componentes além da página web. Não revela a implementação desses serviços. |
| Consulta de impressoras e envio de documentos estruturados | 227.900–229.500; 2.750.500–2.751.500 | O frontend monta o documento e chama o servidor local. Não comprova compatibilidade com toda marca/modelo. |
| Paleta de páginas, filtragem por permissão, normalização de acentos e histórico local de páginas recentes | 936.000–939.500 | Há busca de navegação. Ela é distinta da busca de produtos e da pesquisa de pedidos no servidor. |
| Normalização de acentos em vários pontos e análise do asterisco na busca do PDV | ocorrências registradas na coleta focada | Referência para uma busca tolerante e uma entrada rápida de quantidade. Não foi feito pedido no concorrente. |
| Perfis de impressoras com parâmetros por modelo, inclusive Elgin | a partir de 8.818.800 | Existe configuração específica de equipamentos; isso não equivale a suporte universal automático. |

Corroboração pública: [manual do totem](https://ajuda.beefood.com.br/manuais/totem-configurar), [fichas do PDV](https://ajuda.beefood.com.br/pdv-fichas), [novidades oficiais](https://beefood.app/novidades). A documentação descreve BeeImpressão e alternativas pelo navegador. A inspeção do frontend não autoriza afirmar que seu backend foi recuperado.

## Melhorias implementadas nesta revisão

| Área | Antes no SeuComércioAqui | Agora |
| --- | --- | --- |
| Busca do cardápio e cadastro | Trecho literal, sensível a acentos e à ordem | Acentos/pontuação normalizados; todas as palavras em qualquer ordem; descrição e categoria pesquisáveis. |
| PDV | Somente trecho do nome; quantidade começava em 1 | Mesma busca do cardápio; referência exata `#id`; `3* produto` preenche a quantidade; Enter abre um resultado único disponível. Opções e confirmação continuam obrigatórias. Limite de 1 a 50 unidades. |
| Pedidos e clientes | Nome/número ou telefone em formato literal | Nome sem acentos, telefone com ou sem pontuação e, nos pedidos, endereço/bairro. Mantidos filtros de situação e limites do histórico. |
| Navegação | Procurar visualmente no menu | Botão de busca, Ctrl+K/Cmd+K, setas/Enter/Esc e páginas recentes. Lista deriva exclusivamente do menu permitido para a pessoa. Histórico local contém apenas IDs de páginas, separado por loja/usuário. |
| Relatórios térmicos | PDF A4, Excel e CSV | Resumo em bobina 58/80 mm com prévia, vendas, recebimentos líquidos por forma real e produtos. Usa a fila de impressão dos pedidos. |
| Interpretação financeira | Coluna de pedidos totalmente pagos chamada “Já recebido” | Rótulo explicita valor de pedidos quitados. Recebimentos parciais/mistos e estornos continuam na tabela de formas reais; o resumo informa o critério por criação do pedido. |
| Fila de impressão | Implementação interna só dos pedidos | Módulo compartilhado entre pedidos, vias de produção/entrega e resumo. Documento e preferências capturados ao enfileirar; cancelamento não significa impressão física. |

## Comparação operacional e trabalho restante

| Área | Situação verificável no nosso código | Lacuna para uma operação mais completa |
| --- | --- | --- |
| PDV, caixa e recebimentos | Implementados; validação de preços/estoque, turno, pagamentos parciais/mistos e estornos | TEF, conciliação bancária e cartão online exigem integração e homologação. |
| Mesas e comandas | Contas, consumo, transferência e fechamento validado | Taxa de serviço, desconto da conta, QR de autoatendimento por mesa e experiência dedicada de garçom. |
| Cozinha e impressão | Etapa por item/setor, filas e impressoras via driver do Windows/navegador | Aplicativo local próprio, roteamento entre várias impressoras, ESC/POS e gaveta. Não foram implementados nesta revisão. |
| Estoque e produção | Insumos, opções com receita, sabores, reservas e lotes/custo médio | Biblioteca central de complementos; compras vinculadas a entrada/conta; produção em cascata e rendimento. |
| Promoções e aceite | Regras por canal/data/horário e aceite automático já existem | Fluxos avançados precisam ser comparados e testados em operação; não são uma ausência total. |
| CRM e WhatsApp | Segmentos E/OU, RFV explícito, caixa de entrada humana, bot por palavras-chave, fila e consentimento | Gatilhos automáticos de aniversário/abandono/segunda compra, pedidos por IA e mídia completa. Provedor e worker precisam de configuração real. |
| Fidelidade | Benefício por número de pedidos e carteira de cashback com reserva/estorno | Programa de pontos com catálogo de recompensas; relatórios especializados. |
| Entregas | CEP/faixa, frete, lotes, links revogáveis e localização voluntária | Otimização de rotas, geocodificação, polígonos e acompanhamento contínuo. |
| Rede | Convite, acesso e diretório de unidades | Consolidação financeira e gestão de catálogo entre filiais. |
| Fiscal e marketplaces | Sem emissão fiscal/integração oficial ativada | Exigem fornecedores, credenciamento, contratos e homologação. Não substituir por telas que apenas simulam conexão. |
| API para parceiros/MCP | APIs internas autenticadas | Credenciais com escopos, contratos externos, versionamento e webhooks assinados; não expor a API administrativa diretamente. |
| Escala Brasil | Fuso por loja, PostgreSQL, isolamento e testes de concorrência existentes | Testes de carga e restauração, métricas/SLA e revisão do bloqueio transacional global do adaptador PostgreSQL. Não há prova de capacidade nacional. |

## Verificação

Testes novos: normalização, ordem de palavras, telefone, referência exata, quantidade, fluxo real de PDV, atalhos e permissões da busca, bobina com prévia e fila, pagamentos parciais/estorno e isolamento entre lojas. Testes anteriores de impressão exercitam seis tamanhos, cancelamento e erro, com comando de impressão substituído por captura controlada. Nenhuma impressora física ou fornecedor financeiro foi homologado nesta execução.

As melhorias foram implementadas com código próprio. Não foi copiado o código proprietário do BeeFood para o projeto. Esta revisão não equivale a concluir todas as lacunas nem a comprovar superioridade de 100%.
