# Impressão, fiscal e relacionamento

Atualização visual de 17/10/2026, sem novos fornecedores, credenciais ou alterações de banco.

- **Imprimir notinha:** ações de teste e prévia em destaque, preferências ao lado de uma prévia ao vivo. Papel, área útil, fonte e via do motoboy atualizam o exemplo. A fila e o documento de impressão existentes permanecem no mesmo fluxo. Preferências continuam locais ao navegador; a prévia não detecta impressoras nem confirma saída física.
- **Fiscal:** página própria para dono e gerente, acessível também pela busca do painel. Exibe explicitamente o estado sem fornecedor e emissão indisponível. Checklist informativo e atalho para impressão de pedidos; não coleta dados fiscais, não chama APIs de emissão e não contrata serviços.
- **Marketing:** atalhos para público, sacolas, campanhas e agendamentos, com cartões de oportunidade calculados a partir dos dados existentes. Preparar campanha abre um rascunho para clientes inativos; não envia mensagens. Agendamentos mantêm as regras, permissões e dependências de conexão já existentes.

Estilos em `static/workspace.css`, limitados às novas superfícies do painel. O cardápio público e o documento impresso não recebem esses estilos.

Validação: testes existentes de impressão, campanhas e busca em Chromium; verificação manual das três páginas em 390, 768 e 1440 px, prévia com bobina de 58 mm/fonte de 16 px/via do motoboy, checklist fiscal, rascunho de recompra e navegação para os agendamentos. Nenhum teste físico de impressora ou integração fiscal foi realizado.
