# SeuComércioAqui

Cardápio digital e gestão de pedidos para pequenos comércios. Frontend responsivo e backend real, com identidade própria em verde-petróleo e lima.

**Aplicação publicada:** [seucomercio-aqui.onrender.com](https://seucomercio-aqui.onrender.com). Para começar, clique em **Criar minha loja**. Veja a [configuração da publicação](docs/DEPLOYMENT.md).

## O que funciona

- Cadastro de lojistas: cada conta tem uma loja e seus próprios dados.
- Cardápio por link, com fotos, categorias, busca e destaques.
- Sacola, complementos, observações, entrega ou retirada e cupom.
- Total calculado no servidor, estoque reservado em transação e proteção contra pedidos duplicados.
- Acompanhamento por link aleatório, sem expor telefone ou endereço do cliente.
- Painel: novos, em preparo, prontos, em entrega, concluídos e cancelados.
- Produtos, upload de fotos, estoque, categorias e cupons.
- Entregadores e atribuição de pedidos.
- Vendas por período, pagamentos confirmados, despesas e exportação CSV.
- Financeiro com custos de produtos e complementos, entrega, taxas de pagamento, comissão e lucro estimado. Custos pendentes impedem exibir um lucro enganoso.
- Cozinha com fichas de produção e atualização dos pedidos; cadastro de pedidos de balcão ou telefone.
- Clientes com histórico de compras; estoque com alertas, ajustes justificados e histórico de movimentações.
- Painel exclusivo do dono da plataforma: lojas, contratos, mensalidades, comissões, recebimentos, despesas, resultado de caixa e histórico administrativo.
- API de entregas com chaves por loja, permissões, revogação, vinculação de pedidos e eventos sem duplicação. Documentação em `/static/api-docs.html`.
- Nome, logo, capa, cor, contato, taxa, pedido mínimo e pagamentos configuráveis.
- Horário de funcionamento por dia (até 3 turnos, inclusive virando a madrugada): a loja abre e fecha sozinha e o cliente vê "abre hoje às 18:00".
- Taxa de entrega por bairro, escolhida pelo cliente no checkout e validada no servidor.
- Alerta sonoro, notificação do navegador e contador no título quando chega pedido novo no painel.
- Botão para o cliente enviar o resumo do pedido no WhatsApp da loja; prévia do link da loja (nome, descrição e foto) ao compartilhar no WhatsApp.
- QR Code do cardápio para imprimir (PNG ou SVG) e ícones para instalar o painel no celular.
- Área do dono da plataforma em **/plataforma**: vendas mês a mês com gráfico e ranking das lojas, exportação CSV, bloqueio/desbloqueio com motivo exibido ao lojista, mensalidade promocional com prazo, mensalidades em aberto no mês, saúde das lojas e avisos/promoções exibidos no painel de todos os lojistas.
- Alteração de senha, logout e recuperação administrativa por comando.

**Pagamentos:** Pix é confirmado manualmente pelo lojista. Dinheiro e cartão são recebidos na entrega ou retirada. Não há gateway bancário, captura de cartão ou confirmação automática de Pix. O link do WhatsApp abre uma conversa com a loja; não envia mensagens automaticamente.

**Plataforma:** mensalidades e comissões configuram contratos; recebimentos são lançados quando efetivamente pagos. Vendas dos lojistas não são receita da plataforma. O conector do MotoJá precisa ser instalado no servidor do parceiro; gerar uma chave aqui não instala esse conector. Veja a [revisão funcional e próximos passos](docs/PRODUCT_REVIEW.md).

## Rodar no computador

Requisitos: Python 3.12 ou superior. Frontend e backend usam o mesmo endereço. Node/npm não são necessários para funcionar.

~~~powershell
git clone https://github.com/Nexusconchal/SeuCom-rcioAqui.git
cd SeuCom-rcioAqui
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
~~~

Abra **http://localhost:8000** e clique em **Criar minha loja**.

1. Cadastre a loja e a conta.
2. Abra Configurações: informe contato, endereço e pagamentos.
3. Cadastre produtos, preços e fotos.
4. Abra a loja pelo botão **Loja fechada**.
5. Copie o link e faça um pedido de teste.

A loja nasce fechada e sem produtos. Nenhuma conta ou senha padrão é instalada. Se usar Pix, informe a chave verdadeira da loja. Estoque vazio significa sem controle de quantidades. Remover categorias move seus produtos para Outros. Produtos são pausados, preservando o histórico.

No Linux/macOS, use .venv/bin/python no lugar de .venv\Scripts\python.exe.

## Demonstração opcional

~~~powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app seed-demo
~~~

O comando pede seu e-mail e senha (mínimo 10 caracteres). Cria **Bistrô da Vila**, fotos e pedidos de exemplo. Visite **/loja/bistro-da-vila** e entre em **/entrar** com a conta criada.

**Dados fictícios: a chave Pix da demo não deve ser usada para pagamento.** A demo não é instalada automaticamente em produção. Fotos externas do Unsplash podem ser substituídas por fotos próprias. Uma ilustração local aparece se a imagem não carregar.

## Hospedar

O GitHub contém o código, não um servidor publicado. Use hospedagem Python/Gunicorn ou Docker com PostgreSQL remoto e Storage, ou **disco persistente** para SQLite. GitHub Pages e hospedagem exclusivamente estática não executam o backend.

| Variável | Produção |
| --- | --- |
| APP_ENV | production |
| SECRET_KEY | Chave aleatória com pelo menos 32 caracteres |
| PUBLIC_URL | URL HTTPS final sem barra no fim |
| TRUSTED_HOSTS | Hosts permitidos, separados por vírgula, sem https:// |
| DATABASE_PATH | Caminho do SQLite no disco persistente |
| UPLOAD_DIR | Diretório das fotos no disco persistente |
| TRUST_PROXY | 1 apenas atrás de um proxy confiável; 0 nos demais casos |
| ALLOW_REGISTRATION | 1 para permitir novas lojas; 0 para fechar cadastros |
| PORT | Porta da hospedagem, padrão 8000 |

Gere a chave:

~~~powershell
python -c "import secrets; print(secrets.token_hex(32))"
~~~

Não coloque segredos no código/GitHub. .env.example documenta os valores; a aplicação lê variáveis de ambiente. No Windows use $env:NOME="valor"; no Linux, export NOME="valor". Em desenvolvimento, sem SECRET_KEY, uma chave temporária é criada e as sessões expiram ao reiniciar.

Comando de produção (Linux):

~~~sh
gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 60 --access-logfile -
~~~

Sem DATABASE_URL, esta configuração usa SQLite em WAL. Com DATABASE_URL, usa PostgreSQL e pode compartilhar dados entre instâncias; configure também o Storage remoto. Não coloque SQLite em filesystem de rede e não use disco efêmero para dados de produção.

### Docker

~~~sh
docker build -t seucomercio-aqui .
docker run --rm -p 8000:8000 \
  -e SECRET_KEY=SUA_CHAVE_ALEATORIA_LONGA \
  -v commerce-data:/data seucomercio-aqui
~~~

Para Docker Compose local, copie .env.example para .env, preencha SECRET_KEY e rode:

~~~sh
docker compose up --build
~~~

O Compose usa HTTP e APP_ENV=development no computador local. Em produção, configure HTTPS, APP_ENV=production, URL final e hosts permitidos. /health verifica serviço e banco.

### Backup e recuperação

Faça backup do banco e das fotos. Com o sistema em uso, use a API de backup do SQLite, não copie apenas o arquivo .sqlite3 enquanto houver escrita/WAL:

~~~sh
python scripts/backup.py /data/seucomercio.sqlite3 /backups/loja.sqlite3
~~~

Guarde a cópia fora do servidor junto com as fotos. Não versione bancos, backups, dados de clientes ou segredos.

Recuperação de senha pelo administrador no servidor:

~~~sh
python -m flask --app app:create_app reset-password --email pessoa@exemplo.com
~~~

O comando pede uma senha nova e invalida sessões anteriores. Recuperação e verificação por e-mail exigem integrar um serviço de envio.

### Render gratuito + Supabase gratuito

A aplicação aceita PostgreSQL remoto em DATABASE_URL e fotos em Storage. Assim os dados sobrevivem a reinicializações do Render sem contratar disco.

Use um projeto Supabase Free, um usuário PostgreSQL exclusivo do backend e o schema privado seucomercio (fora de public). As tabelas habilitam RLS e não concedem acesso público. O usuário do servidor é proprietário das tabelas; o Flask autentica cada lojista e restringe o acesso à sua loja.

Configure no Render: APP_ENV=production, SECRET_KEY aleatória, TRUST_PROXY=1, DATABASE_URL com o **pooler de sessão IPv4 na porta 5432**, DATABASE_SCHEMA=seucomercio, STORAGE_UPLOAD_URL, STORAGE_UPLOAD_TOKEN e STORAGE_PUBLIC_URL. O app usa automaticamente RENDER_EXTERNAL_URL. Inicializa o banco sem apagar dados existentes.

As fotos passam por validação/reprocessamento no Flask, depois são enviadas à função commerce-upload. Ela verifica um token exclusivo do servidor pelo hash SHA-256 antes de acessar o Storage. A chave administrativa do Supabase fica na própria função; não é enviada ao navegador. Crie o bucket commerce-photos público, somente para fotos do cardápio, sem políticas públicas de escrita. Publique a função em supabase/functions/commerce-upload, configurando UPLOAD_TOKEN_SHA256; a verificação JWT da plataforma é substituída por essa autenticação própria. Documentos e dados de clientes não devem ser enviados a esse bucket.

Build: pip install -r requirements.txt. Start: gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60. Health check: /health.

O Render Free adormece após inatividade e pode demorar a abrir novamente. O Supabase Free possui limites de banco/armazenamento e pode pausar projetos inativos. Não há garantia de operação contínua nesse conjunto gratuito. Referências: [Render Free](https://render.com/docs/free), [Supabase Free](https://supabase.com/pricing).

Para backups PostgreSQL, use pg_dump com a conexão da sua conta e copie as fotos separadamente. O script backup.py atende somente SQLite.

## Testes

~~~sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -v
~~~

Para testar só a API, sem Chromium:

~~~sh
python -m pytest tests/test_api.py -v
~~~

GitHub Actions verifica sintaxe, API no Linux e Windows, auditoria de dependências, container de produção e compra/gestão em Chromium. Cobre isolamento entre lojas, preços, estoque concorrente, CSRF, uploads, cupons e fluxo de pedidos. As capturas aparecem no pacote **telas-seucomercio** no resultado da execução.

A suíte também verifica custos históricos, lucro com custos pendentes, permissões do dono da plataforma, lançamentos idempotentes e anulação, chaves de integração, eventos repetidos, revogação e limite por chave. O job PostgreSQL usa um banco descartável e testa o papel restrito do backend. Para usar um Chromium já instalado localmente, defina `PLAYWRIGHT_CHROMIUM_EXECUTABLE` com o caminho do executável.

## Estrutura

~~~text
app.py                    Flask: API, páginas e regras de negócio
business.py               Financeiro, dono da plataforma e API de entregas
migrations.py             Atualizações aditivas SQLite/PostgreSQL
schema.sql                Banco SQLite
seed.py                   Demonstração opcional
static/
  index.html              Entrada da aplicação
  app.js                  Página inicial e acesso
  menu.js                 Cardápio, checkout e acompanhamento
  dashboard.js            Painel do lojista
  management.js           Gestão, clientes, estoque e plataforma
  management.css          Painéis responsivos
  api-docs.html           Contrato público da API de entregas
  ui.js                   Componentes e cliente HTTP
  styles.css              Desktop, celular e impressão
  logo.svg                Marca (sacola com toldo); PNGs gerados por scripts/brand_assets.py
tests/                    Testes da API e do navegador
scripts/backup.py         Backup consistente
Dockerfile                Servidor de produção
docker-compose.yml        Ambiente local persistente
docs/API.md               Endpoints e exemplos
~~~

## Escopo

Esta versão cobre cardápio, pedidos, gestão financeira e administração da plataforma. Disponibiliza uma API de entregas para parceiros; conectores externos ainda precisam ser implementados no parceiro. Não integra emissão fiscal, impressoras via drivers, WhatsApp automático ou conciliação bancária. A impressão usa o navegador.

As sessões são assinadas; senhas usam scrypt; alterações exigem CSRF; preços e estoque são validados pelo servidor; uploads são reprocessados; o painel limita os dados à loja autenticada. O link do pedido mostra itens, valores e status. Os relatórios usam a data de criação do pedido e excluem cancelados. Cancelamentos não executam reembolsos bancários.

Referências: [segurança no Flask](https://flask.palletsprojects.com/en/stable/web-security/), [uploads](https://flask.palletsprojects.com/en/stable/patterns/fileuploads/), [SQLite](https://docs.python.org/3/library/sqlite3.html).
