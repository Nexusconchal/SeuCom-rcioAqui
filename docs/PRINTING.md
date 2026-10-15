# Impressão pelo Windows

O painel usa `window.print()` e a impressão de páginas do Chrome/Edge. A escolha da impressora acontece no diálogo do navegador ou do Windows, usando a impressora instalada e seu driver. O app não enumera impressoras, instala drivers, abre portas COM/USB, envia ESC/POS nem lê o estado físico da impressora. A marca não exige um conector próprio quando o driver aceita impressão de páginas do navegador.

## Preparação em cada computador

1. Instalar o driver oficial do modelo, por USB ou pela interface de rede suportada pelo equipamento. Imprimir primeiro a página de teste do Windows. Apenas instalar uma porta serial virtual não basta se não houver impressora gráfica na lista.
2. Configurar no driver o papel e o comprimento da bobina. Em **Imprimir notinha**, escolher 58, 76, 80, 112 mm, A4 ou outra largura. A área útil padrão é, respectivamente, 48, 68, 72, 104 e 190 mm; outra largura começa em 72 mm e aceita 32 a 200 mm. A configuração é local a este navegador; o setor também é específico da loja.
3. Usar **Ver prévia** e **Imprimir teste**. Escolher o destino, escala 100%, retrato e desativar cabeçalhos/rodapés. As margens CSS são de 4 mm, ajustáveis pelo diálogo/driver. Reduzir a área útil se o driver cortar as laterais. Conferir a linha de 20 mm com régua e os acentos. Letras podem ser 11, 12, 14 ou 16 px; em larguras muito pequenas, usar letras menores para evitar muitas quebras.
4. Guilhotina e avanço dependem da configuração do driver e do modelo. Folha A4 usa o formato A4 no diálogo. O painel não força um comprimento de bobina que possa ser incompatível com o driver. Papel em branco ao final deve ser conferido nas preferências do driver/comprimento do formulário.

Não há garantia de compatibilidade física com todas as impressoras. ECF fiscal, impressoras sem driver de páginas, dispositivos apenas RAW/serial, etiquetas e impressoras embutidas em terminais de pagamento exigem avaliação/conector específico. Esta função imprime pedido/documento não fiscal, sem emitir NFC-e/NF-e.

## Fila e impressão automática

As preferências e o documento são capturados ao enfileirar. O documento seguinte aguarda `afterprint`; esse evento significa fechamento da janela, inclusive cancelamento, e não confirma impressão física. Se `window.print()` lançar erro, a fila é liberada e a tela informa a falha. Não há retentativa automática para evitar duplicação de papel. O painel precisa permanecer aberto para acompanhar pedidos novos.

O atalho opcional com `--kiosk-printing` mantém a configuração existente de Chrome para um computador de caixa dedicado. O caminho do executável, o destino lembrado pelo navegador e a impressão de teste precisam ser conferidos em cada instalação. O site não habilita esse modo remotamente.

## Verificação e limites

`tests/test_printing_browser.py` usa API e Chromium reais com o comando de impressão substituído por uma captura controlada. Verifica seis perfis, largura efetiva em milímetros, fonte grande, acentos, QR da via do entregador, exclusão da interface em mídia print, conteúdo sem transbordamento horizontal, persistência, cancelamento/fila, falha ao abrir impressão e telas 390/768/1440 px. Os PDFs são gerados pelo motor de impressão do Chromium, com tamanhos simulados de papel; não homologam driver, guilhotina, conexão ou hardware de nenhuma marca. Nenhum trabalho foi enviado a uma impressora física.

## Referências oficiais

Em **Gerar relatório**, o formato **Resumo para impressora de notinha** oferece prévia em 58 ou 80 mm. Inclui resumo de gestão, vendas por dia, até 30 produtos e recebimento líquido por forma real dos pedidos criados no período. Não inclui dados individuais de clientes. O PDF/Excel mantém os detalhes de caixa por data da operação. Pedidos e resumos compartilham a fila; antes de imprimir o resumo, encerre a janela anterior. Selecione o mesmo papel no driver e no diálogo.

O comparativo técnico e as diferenças em relação ao serviço local do BeeFood estão em [BEEFOOD_CODE_REVIEW.md](BEEFOOD_CODE_REVIEW.md). O nosso fluxo continua pelo driver/navegador; esta revisão não adiciona um serviço nativo de impressão.

- [Instalar uma impressora no Windows — Microsoft](https://support.microsoft.com/pt-br/windows/hardware/printer/add-or-install-a-printer-in-windows)
- [Imprimir pelo Chrome — Google](https://support.google.com/chrome/answer/1069693?hl=pt-BR)
- [Bematech MP-4200 TH/ADV no Windows — Elgin Developer Community](https://github.com/ElginDeveloperCommunity/Impressoras/wiki/MP4200-TH-%E2%80%90-Instalar-impressora-no-Windows)
- [Drivers e documentação de impressoras Elgin/Bematech](https://github.com/ElginDeveloperCommunity/Impressoras)
